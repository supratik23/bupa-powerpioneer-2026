"""
Orchestrates a wellbeing calculation:

1. extract features from source tables -> ``employee_risk_snapshot`` (one per employee/date)
2. score them                           -> ``wellbeing_score`` + ``risk_label`` on the snapshot
3. record the prediction                -> ``risk_prediction`` + ``risk_explanation`` rows
4. for HIGH / CRITICAL bands, raise follow-up actions in ``intervention`` (deduplicated)
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from chat.notifications import notify_employee

from .features import extract_features
from .models import (
    ActionStatus,
    ActionType,
    ContributionDirection,
    EmployeeRiskSnapshot,
    Intervention,
    RiskBand,
    RiskExplanation,
    RiskPrediction,
)
from .scoring import MODEL_NAME, MODEL_VERSION, calculate_score

INTERVENTION_DEDUP_DAYS = 7


def _d(value):
    return Decimal(str(value))


@transaction.atomic
def calculate_wellbeing(
    employee,
    snapshot_date: date | None = None,
    *,
    is_training_record: bool = False,
    create_interventions: bool = True,
    performed_by=None,
) -> RiskPrediction:
    snapshot_date = snapshot_date or timezone.localdate()
    features = extract_features(employee, snapshot_date)
    result = calculate_score(features.columns, features.survey_score)

    snapshot, _ = EmployeeRiskSnapshot.objects.update_or_create(
        employee=employee,
        snapshot_date=snapshot_date,
        is_training_record=is_training_record,
        defaults={
            **features.columns,
            "wellbeing_score": _d(result.wellbeing_score),
            "risk_label": result.risk_band,
        },
    )

    prediction = RiskPrediction.objects.create(
        employee=employee,
        risk_snapshot=snapshot,
        risk_score=_d(result.risk_score),
        risk_band=result.risk_band,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        predicted_at=timezone.now(),
    )
    RiskExplanation.objects.bulk_create([
        RiskExplanation(
            prediction=prediction,
            feature_name=c.feature_name,
            feature_value=None if c.feature_value is None else _d(c.feature_value),
            shap_value=_d(c.points),
            contribution_direction=(
                ContributionDirection.INCREASES_RISK if c.points > 0 else ContributionDirection.DECREASES_RISK
            ),
            display_order=i,
        )
        for i, c in enumerate(result.contributions)
    ])

    if create_interventions and not is_training_record and result.risk_band in (RiskBand.HIGH, RiskBand.CRITICAL):
        _raise_interventions(employee, prediction, result, performed_by)
    return prediction


def _recent_pending(employee, action_type) -> bool:
    since = timezone.now() - timedelta(days=INTERVENTION_DEDUP_DAYS)
    return Intervention.objects.filter(
        employee=employee, action_type=action_type,
        action_status__in=[ActionStatus.PENDING, ActionStatus.IN_PROGRESS], triggered_at__gte=since,
    ).exists()


def _raise_interventions(employee, prediction, result, performed_by):
    from employees.services import suggest_buddies

    now = timezone.now()
    drivers = [
        {"feature": c.feature_name, "value": c.feature_value, "points": c.points}
        for c in result.contributions if c.points > 0
    ][:5]
    base_payload = {
        "wellbeing_score": result.wellbeing_score,
        "risk_band": result.risk_band,
        "top_drivers": drivers,
        "triggered_by": str(performed_by.pk) if performed_by else "system",
    }
    created = []

    def make(action_type, target=None, status=ActionStatus.PENDING, failure=None, **extra):
        if _recent_pending(employee, action_type):
            return
        created.append(Intervention.objects.create(
            employee=employee, prediction=prediction, target_employee=target, action_type=action_type,
            action_status=status, action_payload={**base_payload, **extra}, failure_reason=failure,
            triggered_at=now, completed_at=now if status == ActionStatus.FAILED else None,
        ))

    manager = employee.manager_employee
    if manager and manager.is_active:
        make(ActionType.NOTIFY_MANAGER, target=manager)
        if result.risk_band == RiskBand.CRITICAL:
            make(ActionType.SCHEDULE_CHECKIN, target=manager, within_hours=48)
    else:
        make(ActionType.NOTIFY_MANAGER, status=ActionStatus.FAILED, failure="No active manager assigned.")

    buddy = employee.buddy_employee
    if buddy and buddy.is_active:
        make(ActionType.NOTIFY_BUDDY, target=buddy)
    else:
        suggestions = [
            {"employee_id": str(s["employee_id"]), "full_name": s["full_name"], "match_score": s["match_score"]}
            for s in suggest_buddies(employee, limit=3)
        ]
        make(ActionType.SUGGEST_BUDDY, target=manager, suggestions=suggestions)

    # Push real-time notifications to recipients connected over WebSocket.
    for iv in created:
        if iv.target_employee_id:
            transaction.on_commit(lambda iv=iv: notify_employee(iv.target_employee_id, {
                "kind": "intervention",
                "intervention_id": str(iv.intervention_id),
                "action_type": iv.action_type,
                "employee_id": str(employee.pk),
                "employee_name": employee.full_name,
                "risk_band": result.risk_band,
            }))


def calculate_for_all(snapshot_date: date | None = None, *, create_interventions=True, performed_by=None):
    from employees.models import Employee

    results = []
    for emp in Employee.objects.filter(is_active=True).select_related("manager_employee", "buddy_employee"):
        results.append(calculate_wellbeing(
            emp, snapshot_date, create_interventions=create_interventions, performed_by=performed_by
        ))
    return results
