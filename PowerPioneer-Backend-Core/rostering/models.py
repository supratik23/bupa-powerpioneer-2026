import uuid

from django.conf import settings
from django.db import models

from common.models import TimeStampedModel


class ShiftType(models.TextChoices):
    DAY = "DAY", "Day"
    EARLY = "EARLY", "Early"
    LATE = "LATE", "Late"
    LONG_DAY = "LONG_DAY", "Long day"
    NIGHT = "NIGHT", "Night"
    ON_CALL = "ON_CALL", "On call"


class ShiftRoster(TimeStampedModel):
    """Table ``shift_roster``: calendar of shifts per employee."""

    shift_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shifts")
    shift_start = models.DateTimeField()
    shift_end = models.DateTimeField()
    planned_hours = models.DecimalField(max_digits=5, decimal_places=2)
    actual_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    shift_type = models.CharField(max_length=20, choices=ShiftType.choices)
    location = models.CharField(max_length=100, null=True, blank=True)
    expected_patient_load = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    actual_patient_load = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    planned_staff_count = models.IntegerField(null=True, blank=True)
    actual_staff_count = models.IntegerField(null=True, blank=True)
    understaffed_flag = models.BooleanField(default=False)
    missed_break_flag = models.BooleanField(default=False)
    short_notice_change_flag = models.BooleanField(default=False)
    redeployment_flag = models.BooleanField(default=False)

    class Meta:
        db_table = "shift_roster"
        ordering = ["-shift_start"]
        indexes = [models.Index(fields=["employee", "shift_start"])]

    def __str__(self):
        return f"{self.employee_id} {self.shift_type} {self.shift_start:%Y-%m-%d %H:%M}"

    @property
    def hours_worked(self) -> float:
        """Actual hours when recorded, otherwise planned hours."""
        return float(self.actual_hours if self.actual_hours is not None else self.planned_hours)


class LeaveType(models.TextChoices):
    ANNUAL = "ANNUAL", "Annual leave"
    SICK = "SICK", "Sick leave"
    MATERNITY = "MATERNITY", "Maternity"
    PATERNITY = "PATERNITY", "Paternity"
    PARENTAL = "PARENTAL", "Parental"
    COMPASSIONATE = "COMPASSIONATE", "Compassionate"
    STUDY = "STUDY", "Study"
    UNPAID = "UNPAID", "Unpaid"
    OTHER = "OTHER", "Other"


class LeaveStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class LeaveRequest(TimeStampedModel):
    """Table ``leave_request``."""

    leave_request_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.CharField(max_length=20, choices=LeaveType.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=LeaveStatus.choices, default=LeaveStatus.PENDING)
    requested_at = models.DateTimeField()
    decision_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leave_request"
        ordering = ["-requested_at"]
        indexes = [models.Index(fields=["employee", "start_date"])]

    def __str__(self):
        return f"{self.employee_id} {self.leave_type} {self.start_date}..{self.end_date} [{self.status}]"

    @property
    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


class AttendanceStatus(models.TextChoices):
    PRESENT = "PRESENT", "Present"
    LATE = "LATE", "Late"
    ABSENT = "ABSENT", "Absent"
    ON_LEAVE = "ON_LEAVE", "On leave"


class AbsenceType(models.TextChoices):
    SICK = "SICK", "Sickness"
    UNPLANNED = "UNPLANNED", "Unplanned"
    UNAUTHORISED = "UNAUTHORISED", "Unauthorised"
    FAMILY_EMERGENCY = "FAMILY_EMERGENCY", "Family emergency"
    PLANNED = "PLANNED", "Planned"


# Absence types that count as "unplanned" for wellbeing scoring
UNPLANNED_ABSENCE_TYPES = {
    AbsenceType.SICK, AbsenceType.UNPLANNED, AbsenceType.UNAUTHORISED, AbsenceType.FAMILY_EMERGENCY,
}


class Attendance(TimeStampedModel):
    """Table ``attendance``. Rows sharing ``absence_episode_id`` belong to one absence episode."""

    attendance_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance")
    attendance_date = models.DateField()
    attendance_status = models.CharField(max_length=20, choices=AttendanceStatus.choices)
    late_minutes = models.IntegerField(default=0)
    absence_type = models.CharField(max_length=20, choices=AbsenceType.choices, null=True, blank=True)
    absence_episode_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "attendance"
        ordering = ["-attendance_date"]
        indexes = [models.Index(fields=["employee", "attendance_date"])]

    def __str__(self):
        return f"{self.employee_id} {self.attendance_date} {self.attendance_status}"


class AppointmentType(models.TextChoices):
    ASSESSMENT = "ASSESSMENT", "Assessment"
    CARE_PLAN_REVIEW = "CARE_PLAN_REVIEW", "Care plan review"
    DOCUMENTATION = "DOCUMENTATION", "Documentation"
    END_OF_LIFE_CARE = "END_OF_LIFE_CARE", "End-of-life care"
    HANDOVER = "HANDOVER", "Handover"
    MEDICATION_ROUND = "MEDICATION_ROUND", "Medication round"
    PERSONAL_CARE = "PERSONAL_CARE", "Personal care"


class AppointmentStatus(models.TextChoices):
    """Values used in appointment.status (no DB constraint; the pipeline writes SCHEDULED)."""

    SCHEDULED = "SCHEDULED", "Scheduled"
    COMPLETED = "COMPLETED", "Completed"


class Appointment(models.Model):
    """
    Table ``appointment``: an employee's scheduled care tasks within a shift day.

    The table is created and filled by the Supabase data pipeline, so Django
    only reads it (``managed = False``: migrations never create or alter it).
    Times are local wall-clock times on ``appointment_date``.
    """

    appointment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name="appointments", db_constraint=False
    )
    appointment_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    title = models.CharField(max_length=200)
    location = models.CharField(max_length=100, null=True, blank=True)
    appointment_type = models.CharField(max_length=40, choices=AppointmentType.choices, null=True, blank=True)
    status = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "appointment"
        ordering = ["appointment_date", "start_time"]

    def __str__(self):
        return f"{self.employee_id} {self.appointment_date} {self.start_time:%H:%M} {self.title}"
