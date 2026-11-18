import mysql.connector
import os
import logging
from typing import Any, Sequence
import psycopg
from psycopg.rows import dict_row
from urllib.parse import quote, unquote
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DBConnectionManager:
    def __init__(self):
        self.host = settings.DB_SERVER_NAME
        self.database = settings.DB_NAME
        self.user = settings.DB_USERNAME
        self.password = settings.DB_PASSKEY

        if not all([self.host, self.database, self.user, self.password]):
            logger.error("Database connection parameters are not fully set in environment variables.")
            raise ValueError("Missing database connection parameters.")
        self.connection = None

    def db_connection(self):
        db_host = self.host
        db_name = self.database
        db_user = self.user
        db_password = self.password

        logger.info(f"Connecting to MySQL database at {db_host} with user {db_user}")

        try:
            self.connection = mysql.connector.connect(
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_password,
                ssl_ca=""
            )
            logger.info(f"Connected to MySQL. Server version: {self.connection.get_server_info()}")
            return self.connection
        except mysql.connector.Error as err:
            logger.error(f"MySQL connection error: {err}")
            return None

    def __enter__(self):
        logger.info("Entering context manager")
        return self 

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.info("Exiting context manager")
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")


class SupabaseDBConnectionManager:
    """
    Connection manager for the Supabase Postgres database (psycopg 3).
    Same interface as DBConnectionManager: db_connection() -> connection with cursor()/commit(), %s placeholders.

    Configure either SUPABASE_DB_URL (postgresql://... connection string from Supabase dashboard -> Connect)
    or SUPABASE_DB_HOST / SUPABASE_DB_PORT / SUPABASE_DB_NAME / SUPABASE_DB_USER / SUPABASE_DB_PASSWORD.

    Usage:
        with SupabaseDBConnectionManager() as db_manager:
            connection = db_manager.db_connection()
            cursor = connection.cursor()
            cursor.execute("INSERT INTO t (a, b) VALUES (%s, %s)", (1, 2))
            connection.commit()

        with SupabaseDBConnectionManager() as db:
            rows = db.fetch_all("SELECT * FROM t WHERE a = %s", (1,))
    """

    def __init__(self, connect_timeout: int = 10):
        self.db_url = settings.SUPABASE_DB_URL
        self.host = settings.SUPABASE_DB_HOST
        self.port = settings.SUPABASE_DB_PORT
        self.database = settings.SUPABASE_DB_NAME
        self.user = settings.SUPABASE_DB_USER
        self.password = settings.SUPABASE_DB_PASSWORD
        self.sslmode = settings.SUPABASE_DB_SSLMODE
        self.connect_timeout = connect_timeout

        if self.db_url and not self.db_url.startswith(("postgresql://", "postgres://")):
            logger.warning(
                "SUPABASE_DB_URL is not a Postgres connection string (expected postgresql://...). "
                "Ignoring it and using SUPABASE_DB_HOST/USER/PASSWORD. The https://<ref>.supabase.co "
                "project URL is for the REST API, not for direct database connections."
            )
            self.db_url = None

        if self.db_url and self._has_placeholder(self.db_url):
            logger.warning(
                "SUPABASE_DB_URL still contains a placeholder such as [YOUR-PASSWORD]. "
                "Ignoring it and using SUPABASE_DB_HOST/USER/PASSWORD."
            )
            self.db_url = None

        if self.db_url:
            self.db_url = self._escape_url_password(self.db_url)

        if not self.db_url and not all([self.host, self.database, self.user, self.password]):
            logger.error("Supabase database connection parameters are not fully set in environment variables.")
            raise ValueError(
                "Missing Supabase database connection parameters. Set SUPABASE_DB_URL or "
                "SUPABASE_DB_HOST, SUPABASE_DB_NAME, SUPABASE_DB_USER and SUPABASE_DB_PASSWORD."
            )
        self.connection = None

    @staticmethod
    def _has_placeholder(db_url: str) -> bool:
        """True when the connection string was copied from the Supabase dashboard without filling the password."""
        return "[YOUR-" in db_url.upper() or "[PASSWORD]" in db_url.upper()

    @staticmethod
    def _escape_url_password(db_url: str) -> str:
        """
        Percent-encode the password inside postgresql://user:password@host/db when it contains reserved
        characters such as '@', '#', '/' or ':' (Supabase passwords often do). The host starts after the LAST '@'.
        Already-encoded passwords (e.g. '%40') are left unchanged.
        """
        scheme, sep, rest = db_url.partition("://")
        if not sep or "@" not in rest:
            return db_url
        # Host, port and database name never contain '@', so the credentials end at the last '@'.
        userinfo, _, hostpart = rest.rpartition("@")
        user, colon, password = userinfo.partition(":")
        if not colon:
            return db_url
        escaped = quote(unquote(password), safe="")
        if escaped != password and not getattr(SupabaseDBConnectionManager, "_escape_warned", False):
            SupabaseDBConnectionManager._escape_warned = True   # log once per process
            logger.warning("SUPABASE_DB_URL password contains reserved characters; percent-encoding it.")
        return f"{scheme}://{user}:{escaped}@{hostpart}"

    def _connect_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "connect_timeout": self.connect_timeout,
            "sslmode": self.sslmode,
            # Supabase's transaction pooler (port 6543) does not support prepared statements.
            "prepare_threshold": None,
        }
        if self.db_url:
            kwargs["conninfo"] = self.db_url
        else:
            kwargs.update(host=self.host, port=self.port, dbname=self.database, user=self.user, password=self.password)
        return kwargs

    def db_connection(self):
        """Open (or reuse) a connection to Supabase Postgres. Returns None if the connection fails."""
        if self.connection is not None and not self.connection.closed:
            return self.connection

        logger.info(f"Connecting to Supabase Postgres at {self.host or 'SUPABASE_DB_URL'} with user {self.user}")
        try:
            self.connection = psycopg.connect(**self._connect_kwargs())
            logger.info(f"Connected to Supabase Postgres. Server version: {self.connection.info.server_version}")
            return self.connection
        except psycopg.Error as err:
            logger.error(f"Supabase Postgres connection error: {err}")
            self.connection = None
            return None

    def _require_connection(self):
        connection = self.db_connection()
        if connection is None:
            raise ConnectionError("Unable to connect to the Supabase database.")
        return connection

    def fetch_all(self, query: str, params: Sequence[Any] | dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a SELECT query and return all rows as dictionaries."""
        with self._require_connection().cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def fetch_one(self, query: str, params: Sequence[Any] | dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Run a SELECT query and return the first row as a dictionary (or None)."""
        with self._require_connection().cursor(row_factory=dict_row) as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()

    def execute(self, query: str, params: Sequence[Any] | dict[str, Any] | None = None, commit: bool = True) -> int:
        """Run an INSERT/UPDATE/DELETE query and return the number of affected rows."""
        connection = self._require_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                affected = cursor.rowcount
            if commit:
                connection.commit()
            return affected
        except Exception:
            connection.rollback()
            raise

    def close(self):
        if self.connection is not None and not self.connection.closed:
            self.connection.close()
            logger.info("Supabase database connection closed")
        self.connection = None

    def __enter__(self):
        logger.info("Entering Supabase context manager")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.info("Exiting Supabase context manager")
        if exc_type is not None and self.connection is not None and not self.connection.closed:
            self.connection.rollback()
        self.close()