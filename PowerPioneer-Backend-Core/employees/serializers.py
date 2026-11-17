from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Employee


class EmployeeBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Employee
        fields = ["employee_id", "employee_number", "full_name", "email", "job_role", "department"]
        read_only_fields = fields


class EmployeeSerializer(serializers.ModelSerializer):
    """
    Full employee record. ``manager_employee_id`` / ``buddy_employee_id`` are accepted on
    create/update but are applied through the assignment rules (see employees.services).
    """

    manager_employee_id = serializers.PrimaryKeyRelatedField(
        source="manager_employee", queryset=Employee.objects.all(), required=False, allow_null=True
    )
    buddy_employee_id = serializers.PrimaryKeyRelatedField(
        source="buddy_employee", queryset=Employee.objects.all(), required=False, allow_null=True
    )
    manager = EmployeeBriefSerializer(source="manager_employee", read_only=True)
    buddy = EmployeeBriefSerializer(source="buddy_employee", read_only=True)
    full_name = serializers.CharField(read_only=True)
    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"},
        help_text="Optional. Set to allow this employee to log in.",
    )

    class Meta:
        model = Employee
        fields = [
            "employee_id", "employee_number", "first_name", "last_name", "full_name", "email",
            "job_role", "department", "location", "manager_employee_id", "buddy_employee_id",
            "manager", "buddy", "employment_type", "contracted_weekly_hours", "hire_date",
            "maternity_return_date", "is_active", "is_staff", "password", "created_at", "updated_at",
        ]
        read_only_fields = ["employee_id", "created_at", "updated_at"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        employee = Employee(**validated_data)
        if password:
            employee.set_password(password)
        else:
            employee.set_unusable_password()
        employee.save()
        return employee

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


# ---------------------------------------------------------------------------
# assignment request bodies
# ---------------------------------------------------------------------------
class AssignManagerSerializer(serializers.Serializer):
    manager_employee_id = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())


class AssignBuddySerializer(serializers.Serializer):
    buddy_employee_id = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())


class RemoveRelationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class BuddySuggestionSerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    full_name = serializers.CharField()
    department = serializers.CharField(allow_null=True)
    location = serializers.CharField(allow_null=True)
    job_role = serializers.CharField()
    current_buddy_load = serializers.IntegerField()
    latest_wellbeing_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    match_score = serializers.FloatField()
    reasons = serializers.ListField(child=serializers.CharField())


class DeactivateResultSerializer(serializers.Serializer):
    employee_id = serializers.UUIDField()
    is_active = serializers.BooleanField()
    direct_reports_reassigned_to = serializers.UUIDField(allow_null=True)
    direct_reports_reassigned = serializers.ListField(child=serializers.UUIDField())
    buddy_assignments_removed = serializers.ListField(child=serializers.UUIDField())


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------
class PowerPioneerTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with email + password. Adds a few claims and the employee profile to the response."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["is_staff"] = user.is_staff
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["employee"] = EmployeeBriefSerializer(self.user).data
        return data


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = Employee
        fields = [
            "employee_id", "employee_number", "first_name", "last_name", "email", "password",
            "job_role", "department", "location", "employment_type", "contracted_weekly_hours",
            "hire_date",
        ]
        read_only_fields = ["employee_id"]

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        return Employee.objects.create_user(password=password, **validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Old password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value
