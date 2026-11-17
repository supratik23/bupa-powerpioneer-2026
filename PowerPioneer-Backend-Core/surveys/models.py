import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class QuestionSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    AI_GENERATED = "AI_GENERATED", "AI generated"
    SYSTEM = "SYSTEM", "System"


class TriggerType(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled pulse"
    RISK_TRIGGERED = "RISK_TRIGGERED", "Risk triggered"
    ONBOARDING = "ONBOARDING", "Onboarding"
    MATERNITY_RETURN = "MATERNITY_RETURN", "Maternity return"
    POST_SHIFT = "POST_SHIFT", "Post shift"
    ADHOC = "ADHOC", "Ad hoc"


class Question(models.Model):
    """
    Table ``question``: master list of questions. ``generated_for_employee`` is set when a
    question was generated for one employee; null means it is for everyone.
    """

    question_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question_text = models.TextField()
    source = models.CharField(max_length=20, choices=QuestionSource.choices, default=QuestionSource.MANUAL)
    trigger_type = models.CharField(max_length=20, choices=TriggerType.choices, default=TriggerType.SCHEDULED)
    generated_for_employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="generated_questions"
    )
    context_data = models.JSONField(null=True, blank=True)
    model_name = models.CharField(max_length=100, null=True, blank=True)
    prompt_version = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question"
        ordering = ["-created_at"]

    def __str__(self):
        return self.question_text[:80]

    @property
    def is_open(self) -> bool:
        return self.is_active and (self.expires_at is None or self.expires_at > timezone.now())


class QuestionOption(models.Model):
    """
    Table ``question_option``. ``normalized_score``: higher means better wellbeing.
    Scores are normalised per question (min..max of its options) when scoring, so
    any scale (1-5, 0-10, 0-100) works.
    """

    option_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    option_text = models.TextField()
    normalized_score = models.SmallIntegerField()
    display_order = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_option"
        ordering = ["question", "display_order"]

    def __str__(self):
        return f"{self.option_text} ({self.normalized_score})"


class EmployeeResponse(models.Model):
    """Table ``employee_response``."""

    response_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="responses")
    option = models.ForeignKey(QuestionOption, on_delete=models.CASCADE, related_name="responses")
    responded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "employee_response"
        ordering = ["-responded_at"]
        indexes = [models.Index(fields=["employee", "responded_at"])]

    def __str__(self):
        return f"{self.employee_id} -> {self.option_id}"
