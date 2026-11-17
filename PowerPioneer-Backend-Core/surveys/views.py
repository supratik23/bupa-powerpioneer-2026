from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.mixins import EmployeeScopedViewSetMixin
from common.permissions import IsStaffOrReadOnly, ensure, is_staff

from .models import EmployeeResponse, Question, QuestionOption
from .serializers import (
    AnswerSerializer,
    EmployeeResponseSerializer,
    QuestionOptionSerializer,
    QuestionSerializer,
)


@extend_schema(tags=["Questions"])
class QuestionViewSet(viewsets.ModelViewSet):
    """Question master data. Read for everyone, write for staff."""

    queryset = Question.objects.prefetch_related("options")
    serializer_class = QuestionSerializer
    permission_classes = [IsStaffOrReadOnly]
    filterset_fields = ["source", "trigger_type", "is_active", "generated_for_employee"]
    search_fields = ["question_text"]
    ordering_fields = ["created_at", "expires_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if getattr(self, "swagger_fake_view", False) or is_staff(user):
            return qs
        # Non-staff never see questions generated for somebody else.
        return qs.filter(Q(generated_for_employee__isnull=True) | Q(generated_for_employee=user))

    def get_permissions(self):
        if self.action in {"pending", "answer"}:
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    @extend_schema(summary="Open questions the current employee has not answered yet",
                   responses=QuestionSerializer(many=True))
    @action(detail=False, methods=["get"])
    def pending(self, request):
        user = request.user
        qs = (
            Question.objects.prefetch_related("options")
            .filter(is_active=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .filter(Q(generated_for_employee__isnull=True) | Q(generated_for_employee=user))
            .exclude(responses__employee=user)
        )
        page = self.paginate_queryset(qs)
        serializer = QuestionSerializer(page if page is not None else qs, many=True)
        return self.get_paginated_response(serializer.data) if page is not None else Response(serializer.data)

    @extend_schema(summary="Answer this question as the current employee", request=AnswerSerializer,
                   responses={201: EmployeeResponseSerializer})
    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        question = self.get_object()
        body = AnswerSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        serializer = EmployeeResponseSerializer(
            data={"question_id": question.pk, "option_id": body.validated_data["option_id"].pk},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Question options"])
class QuestionOptionViewSet(viewsets.ModelViewSet):
    queryset = QuestionOption.objects.select_related("question")
    serializer_class = QuestionOptionSerializer
    permission_classes = [IsStaffOrReadOnly]
    filterset_fields = ["question"]
    ordering_fields = ["display_order", "normalized_score"]


@extend_schema(tags=["Employee responses"])
class EmployeeResponseViewSet(EmployeeScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Survey answers. Employees create their own; managers can read their reports' answers;
    only staff may edit or delete.
    """

    queryset = EmployeeResponse.objects.select_related("employee", "question", "option")
    serializer_class = EmployeeResponseSerializer
    filterset_fields = {
        "employee": ["exact"],
        "question": ["exact"],
        "option": ["exact"],
        "responded_at": ["gte", "lte"],
    }
    ordering_fields = ["responded_at"]

    def check_write(self, employee):
        user = self.request.user
        if self.action == "create":
            ensure(is_staff(user) or employee.pk == user.pk, "You can only answer for yourself.")
        else:
            ensure(is_staff(user), "Only staff can modify or delete responses.")
