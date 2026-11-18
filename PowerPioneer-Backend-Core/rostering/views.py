from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from common.mixins import EmployeeScopedViewSetMixin
from common.permissions import can_manage, ensure

from .models import Appointment, AppointmentStatus, Attendance, LeaveRequest, LeaveStatus, ShiftRoster
from .serializers import (
    AppointmentSerializer,
    AttendanceSerializer,
    LeaveDecisionSerializer,
    LeaveRequestSerializer,
    ShiftRosterSerializer,
)


@extend_schema(tags=["Shift roster"])
class ShiftRosterViewSet(EmployeeScopedViewSetMixin, viewsets.ModelViewSet):
    """Shifts. Writable by staff or the employee's manager."""

    queryset = ShiftRoster.objects.select_related("employee")
    serializer_class = ShiftRosterSerializer
    filterset_fields = {
        "employee": ["exact"],
        "shift_type": ["exact"],
        "location": ["exact"],
        "shift_start": ["gte", "lte"],
        "understaffed_flag": ["exact"],
        "missed_break_flag": ["exact"],
        "short_notice_change_flag": ["exact"],
        "redeployment_flag": ["exact"],
    }
    ordering_fields = ["shift_start", "shift_end", "created_at"]


@extend_schema(tags=["Leave requests"])
class LeaveRequestViewSet(EmployeeScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Leave requests. Employees can raise and edit their own (status stays PENDING);
    staff or the manager approve/reject.
    """

    queryset = LeaveRequest.objects.select_related("employee")
    serializer_class = LeaveRequestSerializer
    allow_self_write = True
    filterset_fields = {
        "employee": ["exact"],
        "leave_type": ["exact"],
        "status": ["exact"],
        "start_date": ["gte", "lte"],
        "end_date": ["gte", "lte"],
    }
    ordering_fields = ["requested_at", "start_date", "end_date"]

    def _guard_status(self, serializer, employee):
        """Only staff/manager may set a status other than PENDING directly."""
        status = serializer.validated_data.get("status")
        if status and status != LeaveStatus.PENDING and not can_manage(self.request.user, employee):
            raise ValidationError({"status": "Use the approve/reject/cancel endpoints to change status."})

    def perform_create(self, serializer):
        employee = serializer.validated_data["employee"]
        self.check_write(employee)
        self._guard_status(serializer, employee)
        status = serializer.validated_data.get("status")
        decision_at = timezone.now() if status and status != LeaveStatus.PENDING else None
        serializer.save(decision_at=decision_at)

    def perform_update(self, serializer):
        self.check_write(serializer.instance.employee)
        self._guard_status(serializer, serializer.instance.employee)
        if serializer.instance.status != LeaveStatus.PENDING and not can_manage(
            self.request.user, serializer.instance.employee
        ):
            raise ValidationError({"detail": "Only pending requests can be edited."})
        super().perform_update(serializer)

    def _decide(self, request, new_status, allowed_from):
        leave = self.get_object()
        LeaveDecisionSerializer(data=request.data).is_valid(raise_exception=True)
        if leave.status not in allowed_from:
            raise ValidationError({"status": f"Cannot move from {leave.status} to {new_status}."})
        leave.status = new_status
        leave.decision_at = timezone.now()
        leave.save(update_fields=["status", "decision_at", "updated_at"])
        return Response(self.get_serializer(leave).data)

    @extend_schema(summary="Approve (staff or manager)", request=LeaveDecisionSerializer,
                   responses=LeaveRequestSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        ensure(can_manage(request.user, self.get_object().employee), "Only staff or the manager can approve.")
        return self._decide(request, LeaveStatus.APPROVED, {LeaveStatus.PENDING})

    @extend_schema(summary="Reject (staff or manager)", request=LeaveDecisionSerializer,
                   responses=LeaveRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        ensure(can_manage(request.user, self.get_object().employee), "Only staff or the manager can reject.")
        return self._decide(request, LeaveStatus.REJECTED, {LeaveStatus.PENDING})

    @extend_schema(summary="Cancel (employee, manager or staff)", request=LeaveDecisionSerializer,
                   responses=LeaveRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        self.check_write(self.get_object().employee)
        return self._decide(request, LeaveStatus.CANCELLED, {LeaveStatus.PENDING, LeaveStatus.APPROVED})


@extend_schema(tags=["Attendance"])
class AttendanceViewSet(EmployeeScopedViewSetMixin, viewsets.ModelViewSet):
    """Attendance records. Writable by staff or the employee's manager."""

    queryset = Attendance.objects.select_related("employee")
    serializer_class = AttendanceSerializer
    filterset_fields = {
        "employee": ["exact"],
        "attendance_status": ["exact"],
        "absence_type": ["exact"],
        "absence_episode_id": ["exact"],
        "attendance_date": ["gte", "lte"],
    }
    ordering_fields = ["attendance_date", "late_minutes"]


@extend_schema(tags=["Appointments"])
class AppointmentViewSet(EmployeeScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Daily appointments (care tasks) from the Supabase ``appointment`` table.
    Employees see their own; managers see their direct reports'; staff see all.
    Rows are created by the data pipeline; the only write is marking one
    complete / reopening it (the employee themself, their manager or staff).
    """

    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    filterset_fields = {
        "employee": ["exact"],
        "appointment_date": ["exact", "gte", "lte"],
        "appointment_type": ["exact"],
        "status": ["exact"],
    }
    ordering_fields = ["appointment_date", "start_time"]

    def _set_status(self, request, status):
        appointment = self.get_object()
        ensure(
            appointment.employee_id == request.user.pk or can_manage(request.user, appointment.employee),
            "Only the employee, their manager or staff can update this appointment.",
        )
        appointment.status = status
        appointment.save(update_fields=["status"])
        return Response(AppointmentSerializer(appointment).data)

    @extend_schema(summary="Mark an appointment completed", request=None, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._set_status(request, AppointmentStatus.COMPLETED)

    @extend_schema(summary="Undo completion (back to SCHEDULED)", request=None, responses=AppointmentSerializer)
    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._set_status(request, AppointmentStatus.SCHEDULED)
