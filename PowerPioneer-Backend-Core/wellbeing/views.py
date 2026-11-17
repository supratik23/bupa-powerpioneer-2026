from collections import Counter

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
