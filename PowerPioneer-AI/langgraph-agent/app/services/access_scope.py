"""
Who is asking the chat agent, and which employees they may see.

The agent endpoints verify the caller with Django and put a `Caller` into the LangGraph run config. The tool wrapper
(app/tools/registry.py) copies it into the CURRENT_CALLER context variable for the duration of each tool call, and the
data helpers read it:

    staff (is_staff)   -> every employee
    manager            -> their direct reports (and themselves)
    nobody set         -> no restriction (background jobs, the check-in pipeline, the stdio MCP servers)
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    employee_id: str
    name: str = ""
    is_staff: bool = False
    is_manager: bool = False

    def as_config(self) -> dict:
        return {"employee_id": self.employee_id, "name": self.name, "is_staff": self.is_staff,
                "is_manager": self.is_manager}

    @classmethod
    def from_config(cls, value) -> "Caller | None":
        if isinstance(value, Caller):
            return value
        if isinstance(value, dict) and value.get("employee_id"):
            return cls(str(value["employee_id"]), value.get("name") or "", bool(value.get("is_staff")),
                       bool(value.get("is_manager")))
        return None


CURRENT_CALLER: contextvars.ContextVar[Caller | None] = contextvars.ContextVar("shiftguard_caller", default=None)


def scoped_manager_id() -> str | None:
    """The manager whose team limits the data, or None when there is no limit (staff / no caller)."""
    caller = CURRENT_CALLER.get()
    if caller is None or caller.is_staff:
        return None
    return caller.employee_id


def team_filter_sql(alias: str = "e") -> tuple[str, list]:
    """SQL fragment (starting with AND) limiting `alias` to the caller's team, plus its parameters."""
    manager_id = scoped_manager_id()
    if manager_id is None:
        return "", []
    return f" AND ({alias}.manager_employee_id = %s OR {alias}.employee_id = %s)", [manager_id, manager_id]


def can_see(employee_row: dict) -> bool:
    manager_id = scoped_manager_id()
    if manager_id is None:
        return True
    return str(employee_row.get("manager_employee_id") or "") == manager_id or str(employee_row["employee_id"]) == manager_id
