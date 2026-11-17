"""
Business logic for the reporting line (manager) and peer-support (buddy) relationships.

Rules
-----
Manager
  * an employee cannot manage themself
  * both employees must be active
  * no cycles: the new manager cannot be anywhere below the employee in the chain
  * the manager cannot simultaneously be the employee's buddy
Buddy
  * an employee cannot be their own buddy
  * both employees must be active
  * a buddy is a peer: it cannot be the employee's manager or a direct report
  * a buddy supports at most ``settings.BUDDY_MAX_ASSIGNEES`` active employees

Every change is recorded in the ``intervention`` table (action_status=COMPLETED)
so there is an audit trail of who changed which relationship.
"""
from django.conf import settings
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Employee


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _jsonable(value):
    """UUIDs and other non-JSON scalars are stored as strings."""
    if value is None or isinstance(value, (bool, int, float, str, list, dict)):
        return value
    return str(value)


def _log(employee, action_type, target=None, performed_by=None, **payload):
    from wellbeing.models import ActionStatus, Intervention

    now = timezone.now()
    payload["performed_by"] = str(performed_by.pk) if performed_by else None
    return Intervention.objects.create(
        employee=employee,
        target_employee=target,
        action_type=action_type,
        action_status=ActionStatus.COMPLETED,
        action_payload={k: _jsonable(v) for k, v in payload.items()},
        triggered_at=now,
        completed_at=now,
    )


def _require_active(*employees):
    for e in employees:
        if not e.is_active:
            raise ValidationError({"detail": f"{e.full_name} is not active."})


def is_in_reporting_chain_below(candidate_manager: Employee, employee: Employee) -> bool:
    """True if ``candidate_manager`` reports (directly or indirectly) to ``employee``."""
    seen = set()
    current = candidate_manager
    while current is not None and current.pk not in seen:
        if current.manager_employee_id == employee.pk:
            return True
        seen.add(current.pk)
        current = current.manager_employee
    return False


def buddy_load(buddy: Employee, exclude: Employee | None = None) -> int:
    qs = buddy.buddy_assignees.filter(is_active=True)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.count()


# ---------------------------------------------------------------------------
# manager
# ---------------------------------------------------------------------------
@transaction.atomic
def assign_manager(employee: Employee, manager: Employee, performed_by=None) -> Employee:
    if manager.pk == employee.pk:
        raise ValidationError({"manager_employee_id": "An employee cannot be their own manager."})
    _require_active(employee, manager)
    if is_in_reporting_chain_below(manager, employee):
        raise ValidationError(
            {"manager_employee_id": f"{manager.full_name} reports to {employee.full_name}; this would create a cycle."}
        )
    if employee.buddy_employee_id == manager.pk:
        raise ValidationError(
            {"manager_employee_id": "This person is currently the employee's buddy. Remove the buddy first."}
        )
    if employee.manager_employee_id == manager.pk:
        return employee  # idempotent

    previous = employee.manager_employee
    employee.manager_employee = manager
    employee.save(update_fields=["manager_employee", "updated_at"])
    _log(
        employee, "ASSIGN_MANAGER", target=manager, performed_by=performed_by,
        previous_manager_employee_id=previous.pk if previous else None,
    )
    return employee


@transaction.atomic
def remove_manager(employee: Employee, performed_by=None, reason: str | None = None) -> Employee:
    if employee.manager_employee_id is None:
        raise ValidationError({"detail": "Employee has no manager assigned."})
    previous = employee.manager_employee
    employee.manager_employee = None
    employee.save(update_fields=["manager_employee", "updated_at"])
    _log(employee, "REMOVE_MANAGER", target=previous, performed_by=performed_by, reason=reason)
    return employee


# ---------------------------------------------------------------------------
# buddy
# ---------------------------------------------------------------------------
@transaction.atomic
def assign_buddy(employee: Employee, buddy: Employee, performed_by=None) -> Employee:
    if buddy.pk == employee.pk:
        raise ValidationError({"buddy_employee_id": "An employee cannot be their own buddy."})
    _require_active(employee, buddy)
    if employee.manager_employee_id == buddy.pk:
        raise ValidationError({"buddy_employee_id": "A manager cannot be the buddy of their direct report."})
    if buddy.manager_employee_id == employee.pk:
        raise ValidationError({"buddy_employee_id": "A direct report cannot be their manager's buddy."})
    if employee.buddy_employee_id == buddy.pk:
        return employee  # idempotent
    limit = settings.BUDDY_MAX_ASSIGNEES
    if buddy_load(buddy, exclude=employee) >= limit:
        raise ValidationError(
            {"buddy_employee_id": f"{buddy.full_name} already supports {limit} employees (maximum)."}
        )

    previous = employee.buddy_employee
    employee.buddy_employee = buddy
    employee.save(update_fields=["buddy_employee", "updated_at"])
    _log(
        employee, "ASSIGN_BUDDY", target=buddy, performed_by=performed_by,
        previous_buddy_employee_id=previous.pk if previous else None,
    )
    return employee


@transaction.atomic
def remove_buddy(employee: Employee, performed_by=None, reason: str | None = None) -> Employee:
    if employee.buddy_employee_id is None:
        raise ValidationError({"detail": "Employee has no buddy assigned."})
    previous = employee.buddy_employee
    employee.buddy_employee = None
    employee.save(update_fields=["buddy_employee", "updated_at"])
    _log(employee, "REMOVE_BUDDY", target=previous, performed_by=performed_by, reason=reason)
    return employee


def suggest_buddies(employee: Employee, limit: int = 5) -> list[dict]:
    """
    Rank possible buddies for ``employee``.

    Candidates are active peers (not the manager, not a direct report) with spare
    capacity whose latest wellbeing band is not HIGH/CRITICAL. Points are given for
    same department (+3), same location (+2), same job role (+1), at least a year
    of tenure (+1), a good latest wellbeing score (up to +2) and low current load.
    """
    from wellbeing.models import EmployeeRiskSnapshot

    latest = EmployeeRiskSnapshot.objects.filter(employee=OuterRef("pk"), is_training_record=False).order_by(
        "-snapshot_date", "-created_at"
    )
    candidates = (
        Employee.objects.filter(is_active=True)
        .exclude(pk=employee.pk)
        .exclude(pk=employee.manager_employee_id or employee.pk)
        .exclude(manager_employee=employee)
        .annotate(
            load=Count("buddy_assignees", filter=Q(buddy_assignees__is_active=True)),
            latest_score=Subquery(latest.values("wellbeing_score")[:1]),
            latest_label=Subquery(latest.values("risk_label")[:1]),
        )
        .filter(load__lt=settings.BUDDY_MAX_ASSIGNEES)
        # NULL-safe: people without any snapshot yet stay eligible
        .filter(Q(latest_label__isnull=True) | ~Q(latest_label__in=["HIGH", "CRITICAL"]))
    )

    today = timezone.localdate()
    ranked = []
    for c in candidates:
        points, reasons = 0.0, []
        if employee.department and c.department == employee.department:
            points += 3
            reasons.append("same department")
        if employee.location and c.location == employee.location:
            points += 2
            reasons.append("same location")
        if c.job_role == employee.job_role:
            points += 1
            reasons.append("same job role")
        if c.hire_date and (today - c.hire_date).days >= 365:
            points += 1
            reasons.append("1+ year tenure")
        if c.latest_score is not None:
            points += min(2.0, float(c.latest_score) / 50)
            reasons.append(f"wellbeing score {float(c.latest_score):.0f}")
        points -= 0.5 * c.load
        ranked.append(
            {
                "employee_id": c.pk,
                "full_name": c.full_name,
                "department": c.department,
                "location": c.location,
                "job_role": c.job_role,
                "current_buddy_load": c.load,
                "latest_wellbeing_score": c.latest_score,
                "match_score": round(points, 2),
                "reasons": reasons,
            }
        )
    ranked.sort(key=lambda r: r["match_score"], reverse=True)
    return ranked[:limit]


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
@transaction.atomic
def deactivate_employee(employee: Employee, performed_by=None) -> dict:
    """
    Deactivate an employee and clean up relationships:
      * direct reports move up to the leaver's own manager (or become unassigned)
      * employees they were buddying lose that buddy
      * their own buddy link is removed
    """
    if not employee.is_active:
        raise ValidationError({"detail": "Employee is already inactive."})

    new_manager = employee.manager_employee
    reassigned, unbuddied = [], []

    for report in employee.direct_reports.all():
        report.manager_employee = new_manager
        report.save(update_fields=["manager_employee", "updated_at"])
        _log(report, "ASSIGN_MANAGER" if new_manager else "REMOVE_MANAGER", target=new_manager,
             performed_by=performed_by, reason=f"previous manager {employee.pk} deactivated")
        reassigned.append(str(report.pk))

    for assignee in employee.buddy_assignees.all():
        assignee.buddy_employee = None
        assignee.save(update_fields=["buddy_employee", "updated_at"])
        _log(assignee, "REMOVE_BUDDY", target=employee, performed_by=performed_by,
             reason="buddy deactivated")
        unbuddied.append(str(assignee.pk))

    employee.is_active = False
    employee.buddy_employee = None
    employee.save(update_fields=["is_active", "buddy_employee", "updated_at"])

    return {
        "employee_id": str(employee.pk),
        "is_active": False,
        "direct_reports_reassigned_to": str(new_manager.pk) if new_manager else None,
        "direct_reports_reassigned": reassigned,
        "buddy_assignments_removed": unbuddied,
    }
