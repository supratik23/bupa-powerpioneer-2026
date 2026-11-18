from datetime import timedelta
from fastmcp import FastMCP
from services.db_service import SupabaseDBConnectionManager
from services.shiftguard_repository import (
    EMPLOYEE_COLUMNS, EMPLOYEE_FROM, ToolInputError, dumps, latest_xgboost_prediction, parse_date,
    resolve_employee, shape_employee, to_jsonable,
)
from services.risk_feature_service import _utc, is_night_shift, hours_worked
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ShiftGuard Employee Tool")


@mcp.tool()
def find_employees(search: str = "", department: str = "", only_with_recent_shifts: bool = False,
                   as_of_date: str = "", limit: int = 25) -> str:
    """
    Search ShiftGuard employees (table `employee`) and return their ids, contact details, manager and buddy.
    Use this first whenever the user names a person, to get the employee_id the other tools need.

    Args:
        search: Part of a name, an email or an employee_number. Empty returns everyone (up to `limit`).
        department: Optional exact department filter (case-insensitive).
        only_with_recent_shifts: True returns only operational staff with shifts in the 30 days up to as_of_date
            (the employees the risk model can score; managers usually have none).
        as_of_date: YYYY-MM-DD used by only_with_recent_shifts. Defaults to today (UTC).
        limit: Maximum rows (1-100).
    """
    try:
        limit = max(1, min(int(limit), 100))
        where, params = ["e.is_active = true"], []
        if search.strip():
            where.append("((e.first_name || ' ' || e.last_name) ILIKE %s OR e.email ILIKE %s OR e.employee_number ILIKE %s)")
            params += [f"%{search.strip()}%"] * 3
        if department.strip():
            where.append("lower(e.department) = lower(%s)")
            params.append(department.strip())
        if only_with_recent_shifts:
            d = parse_date(as_of_date)
            where.append(
                "EXISTS (SELECT 1 FROM shift_roster s WHERE s.employee_id = e.employee_id "
                "AND s.shift_start >= %s AND s.shift_start < %s)"
            )
            params += [_utc(d - timedelta(days=29)), _utc(d + timedelta(days=1))]

        with SupabaseDBConnectionManager() as db:
            rows = db.fetch_all(
                f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} WHERE {' AND '.join(where)} "
                "ORDER BY e.last_name, e.first_name LIMIT %s",
                (*params, limit),
            )
        return dumps({"count": len(rows), "employees": [shape_employee(r) for r in rows]})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("find_employees failed")
        return f"Error searching employees: {e}"


@mcp.tool()
def get_employee_details(employee: str, as_of_date: str = "") -> str:
    """
    Profile of one employee plus a roster summary (last 30 days and next 7 days) and the latest XGBoost risk result.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        as_of_date: YYYY-MM-DD reference date. Defaults to today (UTC).
    """
    try:
        d = parse_date(as_of_date)
        with SupabaseDBConnectionManager() as db:
            row = resolve_employee(db, employee)
            shifts = db.fetch_all(
                "SELECT shift_start, shift_end, planned_hours, actual_hours, shift_type, location, "
                "missed_break_flag, short_notice_change_flag FROM shift_roster "
                "WHERE employee_id = %s AND shift_start >= %s AND shift_start < %s ORDER BY shift_start",
                (row["employee_id"], _utc(d - timedelta(days=29)), _utc(d + timedelta(days=8))),
            )
            latest = latest_xgboost_prediction(db, row["employee_id"])

        today_end = _utc(d + timedelta(days=1))
        past = [s for s in shifts if s["shift_start"] < today_end]
        upcoming = [s for s in shifts if s["shift_start"] >= today_end]
        return dumps({
            "employee": shape_employee(row),
            "as_of_date": d,
            "last_30_days": {
                "shifts": len(past),
                "hours_worked": round(sum(hours_worked(s) for s in past), 2),
                "night_shifts": sum(1 for s in past if is_night_shift(s)),
                "missed_breaks": sum(1 for s in past if s["missed_break_flag"]),
                "short_notice_changes": sum(1 for s in past if s["short_notice_change_flag"]),
            },
            "next_7_days": [
                {"shift_start": s["shift_start"], "shift_end": s["shift_end"], "shift_type": s["shift_type"],
                 "location": s["location"]}
                for s in upcoming
            ],
            "latest_risk": to_jsonable(latest),
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("get_employee_details failed")
        return f"Error fetching employee details: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
