from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from common.permissions import IsStaff, IsStaffOrReadOnly, can_manage, ensure

from . import services
from .models import Employee
from .serializers import (
    AssignBuddySerializer,
    AssignManagerSerializer,
    BuddySuggestionSerializer,
    ChangePasswordSerializer,
    DeactivateResultSerializer,
    EmployeeSerializer,
    PowerPioneerTokenObtainPairSerializer,
    RegisterSerializer,
    RemoveRelationSerializer,
)

_UNSET = object()


@extend_schema_view(
    list=extend_schema(summary="List employees"),
    retrieve=extend_schema(summary="Get an employee"),
    create=extend_schema(summary="Create an employee (staff)"),
    update=extend_schema(summary="Replace an employee (staff)"),
    partial_update=extend_schema(summary="Update an employee (staff)"),
    destroy=extend_schema(summary="Hard delete an employee (staff). Prefer /deactivate/."),
)
@extend_schema(tags=["Employees"])
class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related("manager_employee", "buddy_employee")
    serializer_class = EmployeeSerializer
    permission_classes = [IsStaffOrReadOnly]
    filterset_fields = [
        "department", "location", "job_role", "employment_type", "is_active",
        "manager_employee", "buddy_employee",
    ]
    search_fields = ["first_name", "last_name", "email", "employee_number", "job_role"]
    ordering_fields = ["last_name", "first_name", "hire_date", "created_at", "employee_number"]

    # Managers may manage buddies of their own direct reports; checked inside the action.
    manager_actions = {"assign_buddy", "remove_buddy", "suggest_buddies"}

    def get_permissions(self):
        if self.action in self.manager_actions or self.action in {"team", "buddy_assignees"}:
            return [permissions.IsAuthenticated()]
        if self.action in {"assign_manager", "remove_manager", "deactivate"}:
            return [IsStaff()]
        return super().get_permissions()

    # -- CRUD: relationships go through the business rules -----------------
    def _apply_relations(self, employee, manager, buddy):
        user = self.request.user
        if manager is not _UNSET:
            if manager is None:
                if employee.manager_employee_id:
                    services.remove_manager(employee, performed_by=user)
            else:
                services.assign_manager(employee, manager, performed_by=user)
        if buddy is not _UNSET:
            if buddy is None:
                if employee.buddy_employee_id:
                    services.remove_buddy(employee, performed_by=user)
            else:
                services.assign_buddy(employee, buddy, performed_by=user)

    @transaction.atomic
    def perform_create(self, serializer):
        manager = serializer.validated_data.pop("manager_employee", _UNSET)
        buddy = serializer.validated_data.pop("buddy_employee", _UNSET)
        employee = serializer.save()
        self._apply_relations(employee, manager, buddy)

    @transaction.atomic
    def perform_update(self, serializer):
        manager = serializer.validated_data.pop("manager_employee", _UNSET)
        buddy = serializer.validated_data.pop("buddy_employee", _UNSET)
        employee = serializer.save()
        self._apply_relations(employee, manager, buddy)

    def _respond(self, employee):
        employee.refresh_from_db()
        return Response(EmployeeSerializer(employee, context=self.get_serializer_context()).data)

    # -- manager -----------------------------------------------------------
    @extend_schema(summary="Assign a manager (staff)", request=AssignManagerSerializer,
                   responses=EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="assign-manager")
    def assign_manager(self, request, pk=None):
        employee = self.get_object()
        body = AssignManagerSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.assign_manager(employee, body.validated_data["manager_employee_id"], performed_by=request.user)
        return self._respond(employee)

    @extend_schema(summary="Remove the manager (staff)", request=RemoveRelationSerializer,
                   responses=EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="remove-manager")
    def remove_manager(self, request, pk=None):
        employee = self.get_object()
        body = RemoveRelationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.remove_manager(employee, performed_by=request.user, reason=body.validated_data.get("reason"))
        return self._respond(employee)

    # -- buddy -------------------------------------------------------------
    @extend_schema(summary="Assign a buddy (staff or the employee's manager)", request=AssignBuddySerializer,
                   responses=EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="assign-buddy")
    def assign_buddy(self, request, pk=None):
        employee = self.get_object()
        ensure(can_manage(request.user, employee), "Only staff or the employee's manager can assign a buddy.")
        body = AssignBuddySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.assign_buddy(employee, body.validated_data["buddy_employee_id"], performed_by=request.user)
        return self._respond(employee)

    @extend_schema(summary="Remove the buddy (staff or the employee's manager)", request=RemoveRelationSerializer,
                   responses=EmployeeSerializer)
    @action(detail=True, methods=["post"], url_path="remove-buddy")
    def remove_buddy(self, request, pk=None):
        employee = self.get_object()
        ensure(can_manage(request.user, employee), "Only staff or the employee's manager can remove a buddy.")
        body = RemoveRelationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        services.remove_buddy(employee, performed_by=request.user, reason=body.validated_data.get("reason"))
        return self._respond(employee)

    @extend_schema(
        summary="Suggest buddies ranked by fit",
        parameters=[OpenApiParameter("limit", OpenApiTypes.INT, description="Max suggestions (default 5)")],
        responses=BuddySuggestionSerializer(many=True),
    )
    @action(detail=True, methods=["get"], url_path="suggest-buddies")
    def suggest_buddies(self, request, pk=None):
        employee = self.get_object()
        ensure(can_manage(request.user, employee), "Only staff or the employee's manager can view suggestions.")
        try:
            limit = max(1, min(50, int(request.query_params.get("limit", 5))))
        except ValueError:
            limit = 5
        return Response(BuddySuggestionSerializer(services.suggest_buddies(employee, limit), many=True).data)

    # -- relationship views ------------------------------------------------
    @extend_schema(summary="Direct reports of this employee", responses=EmployeeSerializer(many=True))
    @action(detail=True, methods=["get"])
    def team(self, request, pk=None):
        employee = self.get_object()
        qs = employee.direct_reports.select_related("manager_employee", "buddy_employee")
        return Response(EmployeeSerializer(qs, many=True, context=self.get_serializer_context()).data)

    @extend_schema(summary="Employees this person is buddying", responses=EmployeeSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="buddy-assignees")
    def buddy_assignees(self, request, pk=None):
        employee = self.get_object()
        qs = employee.buddy_assignees.select_related("manager_employee", "buddy_employee")
        return Response(EmployeeSerializer(qs, many=True, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Deactivate (staff): reassigns direct reports to the leaver's manager and clears buddy links",
        request=None, responses=DeactivateResultSerializer,
    )
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        employee = self.get_object()
        return Response(services.deactivate_employee(employee, performed_by=request.user))


# ---------------------------------------------------------------------------
# auth views
# ---------------------------------------------------------------------------
@extend_schema(tags=["Auth"], summary="Obtain JWT access + refresh tokens (email + password)")
class LoginView(TokenObtainPairView):
    serializer_class = PowerPioneerTokenObtainPairSerializer


@extend_schema(tags=["Auth"], summary="Self-register an employee account (non-staff)")
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


@extend_schema(tags=["Auth"])
class MeView(generics.RetrieveAPIView):
    """Profile of the currently authenticated employee."""

    serializer_class = EmployeeSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["Auth"], summary="Change own password", request=ChangePasswordSerializer, responses=None)
class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)
