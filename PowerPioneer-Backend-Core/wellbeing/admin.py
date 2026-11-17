from django.contrib import admin

from .models import EmployeeRiskSnapshot, Intervention, RiskExplanation, RiskPrediction


@admin.register(EmployeeRiskSnapshot)
class EmployeeRiskSnapshotAdmin(admin.ModelAdmin):
    list_display = ["employee", "snapshot_date", "wellbeing_score", "risk_label", "is_training_record"]
    list_filter = ["risk_label", "is_training_record"]
    raw_id_fields = ["employee"]


class RiskExplanationInline(admin.TabularInline):
    model = RiskExplanation
    extra = 0


@admin.register(RiskPrediction)
class RiskPredictionAdmin(admin.ModelAdmin):
    list_display = ["employee", "risk_band", "risk_score", "model_name", "model_version", "predicted_at"]
    list_filter = ["risk_band", "model_name"]
    raw_id_fields = ["employee", "risk_snapshot"]
    inlines = [RiskExplanationInline]


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ["employee", "action_type", "action_status", "target_employee", "triggered_at"]
    list_filter = ["action_type", "action_status"]
    raw_id_fields = ["employee", "target_employee", "prediction"]
