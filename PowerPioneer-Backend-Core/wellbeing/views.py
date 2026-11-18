from collections import Counter
from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from common.mixins import EmployeeScopedViewSetMixin
from common.permissions import IsStaff, can_view, ensure, is_staff
from employees.models import Employee

from . import services
from .models import (
    ActionStatus,
    EmployeeRiskSnapshot,
    Intervention,
    RiskExplanation,
    RiskPrediction,
)
from .serializers import (
    CalculateAllRequestSerializer,
    CalculateAllResultSerializer,
    CalculateRequestSerializer,
    EmployeeRiskSnapshotSerializer,
    InterventionSerializer,
    InterventionStatusSerializer,
    NestedExplanationSerializer,
    RiskExplanationSerializer,
    RiskPredictionSerializer,
    WellbeingResultSerializer,
    WellbeingSummarySerializer,
)


class StaffWriteMixin(EmployeeScopedViewSetMixin):
    """Scoped reads; only staff may write (rows are normally produced by the calculator)."""

    def check_write(self, employee):
        ensure(is_staff(self.request.user), "Only staff can modify calculated records.")


@extend_schema(tags=["Risk snapshots"])
class EmployeeRiskSnapshotViewSet(StaffWriteMixin, viewsets.ModelViewSet):
    queryset = EmployeeRiskSnapshot.objects.select_related("employee")
    serializer_class = EmployeeRiskSnapshotSerializer
    filterset_fields = {
        "employee": ["exact"],
        "snapshot_date": ["exact", "gte", "lte"],
        "risk_label": ["exact"],
        "is_training_record": ["exact"],
        "wellbeing_score": ["gte", "lte"],
    }
    ordering_fields = ["snapshot_date", "wellbeing_score", "created_at"]


@extend_schema(tags=["Risk predictions"])
class RiskPredictionViewSet(StaffWriteMixin, viewsets.ModelViewSet):
    queryset = RiskPrediction.objects.select_related("employee", "risk_snapshot").prefetch_related("explanations")
    serializer_class = RiskPredictionSerializer
    filterset_fields = {
        "employee": ["exact"],
        "risk_snapshot": ["exact"],
        "risk_band": ["exact"],
        "model_name": ["exact"],
        "predicted_at": ["gte", "lte"],
    }
    ordering_fields = ["predicted_at", "risk_score"]


@extend_schema(tags=["Risk explanations"])
class RiskExplanationViewSet(StaffWriteMixin, viewsets.ModelViewSet):
    queryset = RiskExplanation.objects.select_related("prediction")
    serializer_class = RiskExplanationSerializer
    employee_field = "prediction__employee"
    filterset_fields = ["prediction", "feature_name", "contribution_direction"]
    ordering_fields = ["display_order", "shap_value"]


@extend_schema(tags=["Interventions"])
class InterventionViewSet(EmployeeScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Interventions. Visible to staff, the employee, their manager and the target employee.
    Created/edited by staff or the employee's manager; the target can start/complete them.
    """

    queryset = Intervention.objects.select_related("employee", "target_employee", "prediction")
    serializer_class = InterventionSerializer
    filterset_fields = {
        "employee": ["exact"],
        "target_employee": ["exact"],
        "prediction": ["exact"],
        "action_type": ["exact"],
        "action_status": ["exact"],
        "triggered_at": ["gte", "lte"],
    }
    ordering_fields = ["triggered_at", "completed_at"]

    def get_queryset(self):
        qs = Intervention.objects.select_related("employee", "target_employee", "prediction")
        user = self.request.user
        if getattr(self, "swagger_fake_view", False) or is_staff(user):
            return qs
        return qs.filter(
            Q(employee=user) | Q(employee__manager_employee=user) | Q(target_employee=user)
        ).distinct()

    def perform_create(self, serializer):
        self.check_write(serializer.validated_data["employee"])
        serializer.save(triggered_at=serializer.validated_data.get("triggered_at") or timezone.now())

    def _transition(self, request, new_status, allowed_from):
        iv = self.get_object()
        user = request.user
        ensure(
            iv.target_employee_id == user.pk or is_staff(user) or iv.employee.manager_employee_id == user.pk,
            "Only the target, the manager or staff can update this intervention.",
        )
        body = InterventionStatusSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        if iv.action_status not in allowed_from:
            raise ValidationError({"action_status": f"Cannot move from {iv.action_status} to {new_status}."})
        iv.action_status = new_status
        if new_status in (ActionStatus.COMPLETED, ActionStatus.FAILED, ActionStatus.CANCELLED):
            iv.completed_at = timezone.now()
        if new_status == ActionStatus.FAILED:
            iv.failure_reason = body.validated_data.get("failure_reason") or "Unspecified"
        iv.save()
        return Response(InterventionSerializer(iv).data)

    open_states = {ActionStatus.PENDING, ActionStatus.IN_PROGRESS}

    @extend_schema(summary="Mark as in progress", request=InterventionStatusSerializer,
                   responses=InterventionSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        return self._transition(request, ActionStatus.IN_PROGRESS, {ActionStatus.PENDING})

    @extend_schema(summary="Mark as completed", request=InterventionStatusSerializer,
                   responses=InterventionSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._transition(request, ActionStatus.COMPLETED, self.open_states)

    @extend_schema(summary="Mark as failed (provide failure_reason)", request=InterventionStatusSerializer,
                   responses=InterventionSerializer)
    @action(detail=True, methods=["post"])
    def fail(self, request, pk=None):
        return self._transition(request, ActionStatus.FAILED, self.open_states)

    @extend_schema(summary="Cancel", request=InterventionStatusSerializer, responses=InterventionSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._transition(request, ActionStatus.CANCELLED, self.open_states)

    # -- in-app notifications for managers / buddies ---------------------------------------------------
    # The AI agent emails the manager/buddy (EMAIL_MANAGER, EMAIL_BUDDY, SCHEDULE_CHECKIN interventions with
    # target_employee = them). The inbox shows the same alerts in the app, one item per colleague, and never
    # gives buddies the risk band or score. "Seen" is stored as action_payload.acknowledged_at.
    INBOX_DAYS = 14
    INBOX_READ_ITEMS = 5
    MANAGER_ALERTS = ("EMAIL_MANAGER", "NOTIFY_MANAGER", "SCHEDULE_CHECKIN")
    BUDDY_ALERTS = ("EMAIL_BUDDY", "NOTIFY_BUDDY")
    BAND_ORDER = {"LOW": 0, "MEDIUM": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    EMAIL_STATE = {"COMPLETED": "sent", "FAILED": "failed", "PENDING": "sending", "IN_PROGRESS": "sending"}

    def _inbox_rows(self, user):
        return (
            Intervention.objects.select_related("employee")
            .filter(
                target_employee=user,
                action_type__in=self.MANAGER_ALERTS + self.BUDDY_ALERTS,
                triggered_at__gte=timezone.now() - timedelta(days=self.INBOX_DAYS),
            )
            .exclude(action_status=ActionStatus.CANCELLED)
            .order_by("-triggered_at")
        )

    @extend_schema(summary="My notifications: colleagues the AI agent asked me (manager/buddy) to support",
                   responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["get"])
    def inbox(self, request):
        by_employee: dict = {}
        for iv in self._inbox_rows(request.user):           # newest first
            by_employee.setdefault(iv.employee_id, []).append(iv)

        items = []
        for rows in by_employee.values():
            unread = [iv for iv in rows if not (iv.action_payload or {}).get("acknowledged_at")]
            group = unread or rows[:1]
            latest, emp = group[0], group[0].employee
            is_manager = any(iv.action_type in self.MANAGER_ALERTS for iv in group)
            schedule = next((iv for iv in group if iv.action_type == "SCHEDULE_CHECKIN"), None)
            email = next((iv for iv in group if iv.action_type.startswith("EMAIL_")), None)
            item = {
                "employee_id": str(emp.pk),
                "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
                "employee_first_name": emp.first_name,
                "job_role": emp.job_role,
                "role": "manager" if is_manager else "buddy",
                "unread": bool(unread),
                "urgent": schedule is not None,
                "due_by": (schedule.triggered_at + timedelta(
                    hours=(schedule.action_payload or {}).get("within_hours", 48))).isoformat() if schedule else None,
                "email_status": self.EMAIL_STATE.get(email.action_status) if email else None,
                "latest_at": latest.triggered_at.isoformat(),
                "alert_count": len(group),
                "risk_band": None,
            }
            if is_manager:   # managers already get the band by email; buddies never see it
                bands = [(iv.action_payload or {}).get("risk_band") for iv in group]
                bands = [b for b in bands if b in self.BAND_ORDER]
                item["risk_band"] = max(bands, key=self.BAND_ORDER.get) if bands else None
            items.append(item)

        unread_items = [i for i in items if i["unread"]]
        read_items = [i for i in items if not i["unread"]][: self.INBOX_READ_ITEMS]
        return Response({"unread_count": len(unread_items), "items": unread_items + read_items})

    @extend_schema(summary="Mark my notifications as seen (one colleague via employee_id, or all)",
                   request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT)
    @action(detail=False, methods=["post"], url_path="inbox/acknowledge")
    def inbox_acknowledge(self, request):
        rows = self._inbox_rows(request.user)
        employee_id = request.data.get("employee_id")
        if employee_id:
            rows = rows.filter(employee_id=employee_id)
        now = timezone.now().isoformat()
        count = 0
        for iv in rows:
            payload = dict(iv.action_payload or {})
            if payload.get("acknowledged_at"):
                continue
            payload["acknowledged_at"] = now
            iv.action_payload = payload
            iv.save(update_fields=["action_payload", "updated_at"])
            count += 1
        return Response({"acknowledged": count})


@extend_schema(tags=["Wellbeing"])
class WellbeingViewSet(viewsets.ViewSet):
    """Wellbeing calculation and summaries."""

    def get_permissions(self):
        if self.action == "calculate_all":
            return [IsStaff()]
        return super().get_permissions()

    @extend_schema(
        summary="Calculate the wellbeing score for one employee",
        description=(
            "Aggregates the last 30/90 days of shifts, attendance, leave and survey answers into an "
            "`employee_risk_snapshot`, scores it, stores a `risk_prediction` with per-feature "
            "`risk_explanation` rows and, for HIGH/CRITICAL bands, raises interventions. "
            "Allowed for staff, the employee and their manager."
        ),
        request=CalculateRequestSerializer,
        responses={201: WellbeingResultSerializer},
    )
    @action(detail=False, methods=["post"])
    def calculate(self, request):
        body = CalculateRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        employee = data["employee_id"]
        ensure(can_view(request.user, employee), "You cannot calculate wellbeing for this employee.")
        if data["is_training_record"]:
            ensure(is_staff(request.user), "Only staff can create training records.")
        prediction = services.calculate_wellbeing(
            employee, data.get("snapshot_date"),
            is_training_record=data["is_training_record"],
            create_interventions=data["create_interventions"],
            performed_by=request.user,
        )
        prediction = RiskPrediction.objects.prefetch_related("explanations").get(pk=prediction.pk)
        return Response(
            {
                "prediction": RiskPredictionSerializer(prediction).data,
                "snapshot": EmployeeRiskSnapshotSerializer(prediction.risk_snapshot).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(summary="Calculate for all active employees (staff)", request=CalculateAllRequestSerializer,
                   responses={201: CalculateAllResultSerializer})
    @action(detail=False, methods=["post"], url_path="calculate-all")
    def calculate_all(self, request):
        body = CalculateAllRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        snapshot_date = body.validated_data.get("snapshot_date") or timezone.localdate()
        results = services.calculate_for_all(
            snapshot_date, create_interventions=body.validated_data["create_interventions"],
            performed_by=request.user,
        )
        return Response(
            {
                "snapshot_date": snapshot_date,
                "employees_scored": len(results),
                "bands": dict(Counter(p.risk_band for p in results)),
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _summary(employee, history_size=10):
        snaps = list(
            EmployeeRiskSnapshot.objects.filter(employee=employee, is_training_record=False)
            .order_by("-snapshot_date")[:history_size]
        )
        latest = snaps[0] if snaps else None
        trend = None
        if len(snaps) > 1 and latest.wellbeing_score is not None and snaps[1].wellbeing_score is not None:
            trend = round(float(latest.wellbeing_score - snaps[1].wellbeing_score), 2)
        drivers = []
        if latest:
            prediction = latest.predictions.order_by("-predicted_at").first()
            if prediction:
                drivers = NestedExplanationSerializer(prediction.explanations.all()[:5], many=True).data
        return {
            "employee_id": employee.pk,
            "full_name": employee.full_name,
            "latest_wellbeing_score": latest.wellbeing_score if latest else None,
            "latest_risk_band": latest.risk_label if latest else None,
            "latest_snapshot_date": latest.snapshot_date if latest else None,
            "trend": trend,
            "history": [
                {"snapshot_date": s.snapshot_date, "wellbeing_score": s.wellbeing_score, "risk_label": s.risk_label}
                for s in reversed(snaps)
            ],
            "top_drivers": drivers,
            "open_interventions": Intervention.objects.filter(
                employee=employee, action_status__in=[ActionStatus.PENDING, ActionStatus.IN_PROGRESS]
            ).count(),
        }

    @extend_schema(
        summary="Wellbeing summary for an employee (latest score, trend, drivers)",
        parameters=[OpenApiParameter("employee_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses=WellbeingSummarySerializer,
    )
    @action(detail=False, methods=["get"], url_path=r"employees/(?P<employee_id>[0-9a-f-]+)")
    def employee_summary(self, request, employee_id=None):
        employee = get_object_or_404(Employee, pk=employee_id)
        ensure(can_view(request.user, employee), "You cannot view this employee's wellbeing.")
        return Response(WellbeingSummarySerializer(self._summary(employee)).data)

    @extend_schema(summary="My wellbeing summary", responses=WellbeingSummarySerializer)
    @action(detail=False, methods=["get"])
    def me(self, request):
        return Response(WellbeingSummarySerializer(self._summary(request.user)).data)

    @extend_schema(summary="Wellbeing summaries for my direct reports (staff: everyone)",
                   responses=WellbeingSummarySerializer(many=True))
    @action(detail=False, methods=["get"])
    def team(self, request):
        user = request.user
        qs = Employee.objects.filter(is_active=True)
        qs = qs if is_staff(user) else qs.filter(manager_employee=user)
        data = [self._summary(e, history_size=5) for e in qs]
        data.sort(key=lambda s: float(s["latest_wellbeing_score"]) if s["latest_wellbeing_score"] is not None else 999)
        return Response(WellbeingSummarySerializer(data, many=True).data)
