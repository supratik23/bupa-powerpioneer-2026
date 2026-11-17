from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from employees.models import Employee

from .models import EmployeeResponse, Question, QuestionOption


class QuestionOptionSerializer(serializers.ModelSerializer):
    question_id = serializers.PrimaryKeyRelatedField(source="question", queryset=Question.objects.all())

    class Meta:
        model = QuestionOption
        fields = ["option_id", "question_id", "option_text", "normalized_score", "display_order", "created_at"]
        read_only_fields = ["option_id", "created_at"]


class NestedOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionOption
        fields = ["option_id", "option_text", "normalized_score", "display_order"]
        read_only_fields = ["option_id"]


class QuestionSerializer(serializers.ModelSerializer):
    """Options can be created inline. On update, sending ``options`` replaces them all."""

    generated_for_employee_id = serializers.PrimaryKeyRelatedField(
        source="generated_for_employee", queryset=Employee.objects.all(), required=False, allow_null=True
    )
    options = NestedOptionSerializer(many=True, required=False)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Question
        fields = [
            "question_id", "question_text", "source", "trigger_type", "generated_for_employee_id",
            "context_data", "model_name", "prompt_version", "is_active", "expires_at", "is_open",
            "options", "created_at",
        ]
        read_only_fields = ["question_id", "created_at"]

    @transaction.atomic
    def create(self, validated_data):
        options = validated_data.pop("options", [])
        question = Question.objects.create(**validated_data)
        for i, opt in enumerate(options):
            opt.setdefault("display_order", i)
            QuestionOption.objects.create(question=question, **opt)
        return question

    @transaction.atomic
    def update(self, instance, validated_data):
        options = validated_data.pop("options", None)
        instance = super().update(instance, validated_data)
        if options is not None:
            if instance.responses.exists():
                raise serializers.ValidationError(
                    {"options": "Question already has responses; edit options individually instead."}
                )
            instance.options.all().delete()
            for i, opt in enumerate(options):
                opt.setdefault("display_order", i)
                QuestionOption.objects.create(question=instance, **opt)
        return instance


class EmployeeResponseSerializer(serializers.ModelSerializer):
    employee_id = serializers.PrimaryKeyRelatedField(
        source="employee", queryset=Employee.objects.all(), required=False,
        help_text="Defaults to the authenticated employee.",
    )
    question_id = serializers.PrimaryKeyRelatedField(source="question", queryset=Question.objects.all())
    option_id = serializers.PrimaryKeyRelatedField(source="option", queryset=QuestionOption.objects.all())
    responded_at = serializers.DateTimeField(required=False)

    class Meta:
        model = EmployeeResponse
        fields = ["response_id", "employee_id", "question_id", "option_id", "responded_at"]
        read_only_fields = ["response_id"]

    def validate(self, attrs):
        if self.instance is None:
            attrs.setdefault("employee", self.context["request"].user)
            attrs.setdefault("responded_at", timezone.now())
        question = attrs.get("question", getattr(self.instance, "question", None))
        option = attrs.get("option", getattr(self.instance, "option", None))
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if option.question_id != question.pk:
            raise serializers.ValidationError({"option_id": "Option does not belong to this question."})
        if self.instance is None and not question.is_open:
            raise serializers.ValidationError({"question_id": "Question is inactive or expired."})
        if question.generated_for_employee_id and question.generated_for_employee_id != employee.pk:
            raise serializers.ValidationError({"question_id": "This question was generated for another employee."})
        return attrs


class AnswerSerializer(serializers.Serializer):
    option_id = serializers.PrimaryKeyRelatedField(queryset=QuestionOption.objects.all())
