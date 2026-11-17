from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import Employee


class EmployeeCreationForm(BaseUserCreationForm):
    class Meta:
        model = Employee
        fields = ("email", "employee_number", "first_name", "last_name", "job_role", "employment_type")


class EmployeeChangeForm(UserChangeForm):
    class Meta:
        model = Employee
        fields = "__all__"


@admin.register(Employee)
class EmployeeAdmin(UserAdmin):
    form = EmployeeChangeForm
    add_form = EmployeeCreationForm
    ordering = ["last_name", "first_name"]
    list_display = ["employee_number", "email", "first_name", "last_name", "job_role",
                    "department", "manager_employee", "buddy_employee", "is_active", "is_staff"]
    list_filter = ["is_active", "is_staff", "department", "employment_type"]
    search_fields = ["email", "first_name", "last_name", "employee_number"]
    raw_id_fields = ["manager_employee", "buddy_employee"]
    readonly_fields = ["created_at", "updated_at", "last_login"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("employee_number", "first_name", "last_name", "job_role", "department",
                                "location", "employment_type", "contracted_weekly_hours", "hire_date",
                                "maternity_return_date")}),
        ("Relationships", {"fields": ("manager_employee", "buddy_employee")}),
        ("Access", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "employee_number", "first_name", "last_name",
                                                 "job_role", "employment_type", "password1", "password2")}),
    )
