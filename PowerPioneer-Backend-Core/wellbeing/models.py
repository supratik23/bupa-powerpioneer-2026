import uuid

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


def Num(null=False):  # noqa: N802 - small factory for schema `numeric` columns
    return models.DecimalField(max_digits=12, decimal_places=4, null=null, blank=null)


class RiskBand(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"            # written by the XGBoost agent
    MODERATE = "MODERATE", "Moderate"      # legacy rule-engine name for MEDIUM
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


class EmployeeRiskSnapshot(TimeStampedModel):
    """
    Table ``employee_risk_snapshot``: features aggregated from roster, attendance,
    leave and survey data up to ``snapshot_date``, plus the calculated wellbeing score.
    """

    risk_snapshot_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_snapshots")
    snapshot_date = models.DateField()
    contracted_hours_30d = Num()
    actual_hours_worked_30d = Num()
    overtime_hours_30d = Num()
    overtime_ratio_30d = Num()
    night_shifts_30d = models.IntegerField(default=0)
    long_shifts_30d = models.IntegerField(default=0)
    max_consecutive_work_days = models.IntegerField(default=0)
    max_consecutive_night_shifts = models.IntegerField(default=0)
    minimum_rest_hours_between_shifts = Num(null=True)
    short_notice_roster_changes_30d = models.IntegerField(default=0)
    missed_breaks_30d = models.IntegerField(default=0)
    unplanned_absence_days_90d = models.IntegerField(default=0)
    unplanned_absence_episodes_90d = models.IntegerField(default=0)
    late_arrivals_30d = models.IntegerField(default=0)
    days_since_last_meaningful_leave = models.IntegerField(null=True, blank=True)
    cancelled_or_rejected_leave_90d = models.IntegerField(default=0)
    understaffed_shift_ratio_30d = Num()
    average_patient_load_ratio_30d = Num(null=True)
    redeployments_90d = models.IntegerField(default=0)
    wellbeing_score = Num(null=True)
    days_since_maternity_return = models.IntegerField(null=True, blank=True)
    return_schedule_variance_hours_30d = Num(null=True)
    overtime_hours_since_maternity_return = Num(null=True)
    maternity_adjustments_fulfilment_ratio = Num(null=True)
    nursing_or_recovery_breaks_missed_30d = models.IntegerField(null=True, blank=True)
    risk_label = models.CharField(max_length=20, choices=RiskBand.choices, null=True, blank=True)
    risk_outcome_within_30d = models.BooleanField(
        null=True, blank=True, help_text="Ground truth for ML training: did a risk event happen within 30 days?"
    )
    is_training_record = models.BooleanField(default=False)

    class Meta:
        db_table = "employee_risk_snapshot"
        ordering = ["-snapshot_date", "-created_at"]
        indexes = [models.Index(fields=["employee", "snapshot_date"])]

    def __str__(self):
        return f"{self.employee_id} @ {self.snapshot_date}: {self.wellbeing_score}"


class RiskPrediction(models.Model):
    """Table ``risk_prediction``."""

    prediction_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_predictions")
    risk_snapshot = models.ForeignKey(EmployeeRiskSnapshot, on_delete=models.CASCADE, related_name="predictions")
    risk_score = Num()
    risk_band = models.CharField(max_length=20, choices=RiskBand.choices)
    model_name = models.CharField(max_length=100)
    model_version = models.CharField(max_length=50)
    predicted_at = models.DateTimeField()

    class Meta:
        db_table = "risk_prediction"
        ordering = ["-predicted_at"]

    def __str__(self):
        return f"{self.employee_id} {self.risk_band} ({self.risk_score})"


class ContributionDirection(models.TextChoices):
    INCREASES_RISK = "INCREASES_RISK", "Increases risk"
    DECREASES_RISK = "DECREASES_RISK", "Decreases risk"


class RiskExplanation(models.Model):
    """Table ``risk_explanation``: per-feature contribution to a prediction."""

    explanation_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prediction = models.ForeignKey(RiskPrediction, on_delete=models.CASCADE, related_name="explanations")
    feature_name = models.CharField(max_length=100)
    feature_value = Num(null=True)
    shap_value = Num()
    contribution_direction = models.CharField(max_length=20, choices=ContributionDirection.choices)
    display_order = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "risk_explanation"
        ordering = ["prediction", "display_order"]

    def __str__(self):
        return f"{self.feature_name}: {self.shap_value}"


class ActionType(models.TextChoices):
    NOTIFY_MANAGER = "NOTIFY_MANAGER", "Notify manager"
    NOTIFY_BUDDY = "NOTIFY_BUDDY", "Notify buddy"
    SUGGEST_BUDDY = "SUGGEST_BUDDY", "Suggest buddy"
    SCHEDULE_CHECKIN = "SCHEDULE_CHECKIN", "Schedule check-in"
    SEND_SURVEY = "SEND_SURVEY", "Send survey"
    SEND_MESSAGE = "SEND_MESSAGE", "Send message"
    ASSIGN_MANAGER = "ASSIGN_MANAGER", "Assign manager"
    REMOVE_MANAGER = "REMOVE_MANAGER", "Remove manager"
    ASSIGN_BUDDY = "ASSIGN_BUDDY", "Assign buddy"
    REMOVE_BUDDY = "REMOVE_BUDDY", "Remove buddy"
    # Written by the ShiftGuard AI agent (allowed by the Supabase CHECK constraint on intervention.action_type)
    EMAIL_MANAGER = "EMAIL_MANAGER", "Email manager"
    EMAIL_BUDDY = "EMAIL_BUDDY", "Email buddy"
    MANAGER_REVIEW = "MANAGER_REVIEW", "Manager review"
    EMPLOYEE_NUDGE = "EMPLOYEE_NUDGE", "Employee nudge"
    FOLLOW_UP_CHECKIN = "FOLLOW_UP_CHECKIN", "Follow-up check-in"
    HR_ESCALATION = "HR_ESCALATION", "HR escalation"
    NO_ACTION = "NO_ACTION", "No action"
    OTHER = "OTHER", "Other"


class ActionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"
    SKIPPED = "SKIPPED", "Skipped"         # e.g. the agent could not email a buddy because none is assigned


class Intervention(TimeStampedModel):
    """
    Table ``intervention``: an action triggered for an employee.
    ``employee`` is the person the intervention concerns; ``target_employee`` is who
    receives or performs it (manager, buddy...).
    """

    intervention_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="interventions")
    prediction = models.ForeignKey(
        RiskPrediction, null=True, blank=True, on_delete=models.SET_NULL, related_name="interventions"
    )
    target_employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="targeted_interventions",
    )
    action_type = models.CharField(max_length=30, choices=ActionType.choices)
    action_status = models.CharField(max_length=20, choices=ActionStatus.choices, default=ActionStatus.PENDING)
    action_payload = models.JSONField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    triggered_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "intervention"
        ordering = ["-triggered_at"]
        indexes = [models.Index(fields=["employee", "triggered_at"])]

    def __str__(self):
        return f"{self.action_type} for {self.employee_id} [{self.action_status}]"
