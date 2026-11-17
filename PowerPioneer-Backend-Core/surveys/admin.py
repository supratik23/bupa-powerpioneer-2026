from django.contrib import admin

from .models import EmployeeResponse, Question, QuestionOption


class QuestionOptionInline(admin.TabularInline):
    model = QuestionOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["question_text", "source", "trigger_type", "generated_for_employee", "is_active", "expires_at"]
    list_filter = ["source", "trigger_type", "is_active"]
    raw_id_fields = ["generated_for_employee"]
    inlines = [QuestionOptionInline]


@admin.register(EmployeeResponse)
class EmployeeResponseAdmin(admin.ModelAdmin):
    list_display = ["employee", "question", "option", "responded_at"]
    raw_id_fields = ["employee", "question", "option"]
