from rest_framework import serializers

from employees.models import Employee

from .models import EmployeeRiskSnapshot, Intervention, RiskExplanation, RiskPrediction


def employee_field(source="employee", **kwargs):
    return serializers.PrimaryKeyRelatedField(source=source, queryset=Employee.objects.all(), **kwargs)


class EmployeeRiskSnapshotSerializer(serializers.ModelSerializer):
    employee_id = employee_field()

    class Meta:
        model = EmployeeRiskSnapshot
        exclude = ["employee"]
        read_only_fields = ["risk_snapshot_id", "created_at", "updated_at"]


class RiskExplanationSerializer(serializers.ModelSerializer):
    prediction_id = serializers.PrimaryKeyRelatedField(source="prediction", queryset=RiskPrediction.objects.all())

    class Meta:
        model = RiskExplanation
        fields = ["explanation_id", "prediction_id", "feature_name", "feature_value", "shap_value",
                  "contribution_direction", "display_order", "created_at"]
        read_only_fields = ["explanation_id", "created_at"]


class NestedExplanationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RiskExplanation
        fields = ["feature_name", "feature_value", "shap_value", "contribution_direction", "display_order"]


class RiskPredictionSerializer(serializers.ModelSerializer):
    employee_id = employee_field()
    risk_snapshot_id = serializers.PrimaryKeyRelatedField(
        source="risk_snapshot", queryset=EmployeeRiskSnapshot.objects.all()
    )
    explanations = NestedExplanationSerializer(many=True, read_only=True)

    class Meta:
        model = RiskPrediction
        fields = ["prediction_id", "employee_id", "risk_snapshot_id", "risk_score", "risk_band",
                  "model_name", "model_version", "predicted_at", "explanations"]
        read_only_fields = ["prediction_id"]

    def validate(self, attrs):
        snapshot = attrs.get("risk_snapshot", getattr(self.instance, "risk_snapshot", None))
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if snapshot and employee and snapshot.employee_id != employee.pk:
            raise serializers.ValidationError({"risk_snapshot_id": "Snapshot belongs to a different employee."})
        return attrs


class InterventionSerializer(serializers.ModelSerializer):
    employee_id = employee_field()
    prediction_id = serializers.PrimaryKeyRelatedField(
        source="prediction", queryset=RiskPrediction.objects.all(), required=False, allow_null=True
    )
    target_employee_id = employee_field(source="target_employee", required=False, allow_null=True)
    triggered_at = serializers.DateTimeField(required=False, help_text="Defaults to now.")

    class Meta:
        model = Intervention
        fields = ["intervention_id", "employee_id", "prediction_id", "target_employee_id", "action_type",
                  "action_status", "action_payload", "failure_reason", "triggered_at", "completed_at",
                  "created_at", "updated_at"]
        read_only_fields = ["intervention_id", "created_at", "updated_at"]

    def validate(self, attrs):
        prediction = attrs.get("prediction", getattr(self.instance, "prediction", None))
        employee = attrs.get("employee", getattr(self.instance, "employee", None))
        if prediction and employee and prediction.employee_id != employee.pk:
            raise serializers.ValidationError({"prediction_id": "Prediction belongs to a different employee."})
        return attrs


class InterventionStatusSerializer(serializers.Serializer):
    failure_reason = serializers.CharField(required=False, allow_blank=True)


# ---------------------------------------------------------------------------
# calculation endpoints
# ---------------------------------------------------------------------------
class CalculateRequestSerializer(serializers.Serializer):
    employee_id = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    snapshot_date = serializers.DateField(required=False, help_text="Defaults to today.")
    is_training_record = serializers.BooleanField(default=False)
    create_interventions = serializers.BooleanField(
        default=True, help_text="Raise follow-up interventions for HIGH/CRITICAL results."
    )


class CalculateAllRequestSerializer(serializers.Serializer):
    snapshot_date = serializers.DateField(required=False)
    create_interventions = serializers.BooleanField(default=True)


class WellbeingResultSerializer(serializers.Serializer):
    prediction = RiskPredictionSerializer()
    snapshot = EmployeeRiskSnapshotSerializer()


class CalculateAllResultSerializer(serializers.Serializer):
    snapshot_date = serializers.DateField()
    employees_scored = serializers.IntegerField()
    bands = serializers.DictField(child=serializers.IntegerField())


class WellbeingSummarySerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    full_name = serializers.CharField()
    latest_wellbeing_score = serializers.DecimalField(max_digits=12, decimal_places=4, allow_null=True)
    latest_risk_band = serializers.CharField(allow_null=True)
    latest_snapshot_date = serializers.DateField(allow_null=True)
    trend = serializers.FloatField(allow_null=True, help_text="Latest score minus the previous snapshot's score.")
    history = serializers.ListField(child=serializers.DictField())
    top_drivers = NestedExplanationSerializer(many=True)
    open_interventions = serializers.IntegerField()
