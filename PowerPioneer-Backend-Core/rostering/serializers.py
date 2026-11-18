from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from employees.models import Employee

from .models import Appointment, AttendanceStatus, Attendance, LeaveRequest, LeaveStatus, ShiftRoster


def employee_field(**kwargs):
    return serializers.PrimaryKeyRelatedField(source="employee", queryset=Employee.objects.all(), **kwargs)


class ShiftRosterSerializer(serializers.ModelSerializer):
    employee_id = employee_field()
    planned_hours = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False,
        help_text="Defaults to the shift duration when omitted.",
    )
    understaffed_flag = serializers.BooleanField(
        required=False, help_text="Defaults to actual_staff_count < planned_staff_count when omitted."
    )

    class Meta:
        model = ShiftRoster
        fields = [
            "shift_id", "employee_id", "shift_start", "shift_end", "planned_hours", "actual_hours",
            "shift_type", "location", "expected_patient_load", "actual_patient_load",
            "planned_staff_count", "actual_staff_count", "understaffed_flag", "missed_break_flag",
            "short_notice_change_flag", "redeployment_flag", "created_at", "updated_at",
        ]
        read_only_fields = ["shift_id", "created_at", "updated_at"]

    def validate(self, attrs):
        start = attrs.get("shift_start", getattr(self.instance, "shift_start", None))
        end = attrs.get("shift_end", getattr(self.instance, "shift_end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"shift_end": "shift_end must be after shift_start."})
        if start and end and "planned_hours" not in attrs and self.instance is None:
            attrs["planned_hours"] = Decimal(str(round((end - start).total_seconds() / 3600, 2)))
        if "understaffed_flag" not in attrs and self.instance is None:
            planned = attrs.get("planned_staff_count")
            actual = attrs.get("actual_staff_count")
            attrs["understaffed_flag"] = bool(planned is not None and actual is not None and actual < planned)
        for f in ("actual_hours", "expected_patient_load", "actual_patient_load",
                  "planned_staff_count", "actual_staff_count"):
            if attrs.get(f) is not None and attrs[f] < 0:
                raise serializers.ValidationError({f: "Must not be negative."})
        return attrs


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_id = employee_field(required=False, help_text="Defaults to the authenticated employee.")
    requested_at = serializers.DateTimeField(required=False, help_text="Defaults to now.")
    duration_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "leave_request_id", "employee_id", "leave_type", "start_date", "end_date", "duration_days",
            "status", "requested_at", "decision_at", "created_at", "updated_at",
        ]
        read_only_fields = ["leave_request_id", "decision_at", "created_at", "updated_at"]

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None:
            attrs.setdefault("employee", request.user)
            attrs.setdefault("requested_at", timezone.now())
            attrs.setdefault("status", LeaveStatus.PENDING)
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_date": "end_date must be on or after start_date."})
        status = attrs.get("status", getattr(self.instance, "status", LeaveStatus.PENDING))
        if status in (LeaveStatus.PENDING, LeaveStatus.APPROVED) and employee and start and end:
            overlap = LeaveRequest.objects.filter(
                employee=employee, status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED],
                start_date__lte=end, end_date__gte=start,
            )
            if self.instance is not None:
                overlap = overlap.exclude(pk=self.instance.pk)
            if overlap.exists():
                raise serializers.ValidationError("Overlaps an existing pending or approved leave request.")
        return attrs


class LeaveDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class AttendanceSerializer(serializers.ModelSerializer):
    employee_id = employee_field()

    class Meta:
        model = Attendance
        fields = [
            "attendance_id", "employee_id", "attendance_date", "attendance_status", "late_minutes",
            "absence_type", "absence_episode_id", "notes", "created_at", "updated_at",
        ]
        read_only_fields = ["attendance_id", "created_at", "updated_at"]

    def validate(self, attrs):
        status = attrs.get("attendance_status", getattr(self.instance, "attendance_status", None))
        late = attrs.get("late_minutes", getattr(self.instance, "late_minutes", 0)) or 0
        absence_type = attrs.get("absence_type", getattr(self.instance, "absence_type", None))
        if late < 0:
            raise serializers.ValidationError({"late_minutes": "Must not be negative."})
        if status == AttendanceStatus.ABSENT and not absence_type:
            raise serializers.ValidationError({"absence_type": "Required when attendance_status is ABSENT."})
        if status != AttendanceStatus.ABSENT and absence_type:
            raise serializers.ValidationError({"absence_type": "Only allowed when attendance_status is ABSENT."})
        return attrs


class AppointmentSerializer(serializers.ModelSerializer):
    """Read-only: appointments are written by the Supabase data pipeline."""

    employee_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "appointment_id", "employee_id", "appointment_date", "start_time", "end_time",
            "title", "location", "appointment_type", "status", "created_at",
        ]
        read_only_fields = fields
