import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class EmploymentType(models.TextChoices):
    FULL_TIME = "FULL_TIME", "Full time"
    PART_TIME = "PART_TIME", "Part time"
    BANK = "BANK", "Bank"
    AGENCY = "AGENCY", "Agency"
    CONTRACT = "CONTRACT", "Contract"


class EmployeeManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("job_role", "Administrator")
        extra_fields.setdefault("employment_type", EmploymentType.FULL_TIME)
        if not extra_fields.get("is_staff") or not extra_fields.get("is_superuser"):
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class Employee(AbstractBaseUser, PermissionsMixin):
    """
    Table ``employee``: users of the application (employees, managers, buddies).

    It is also the Django auth user model, so it carries the auth columns
    ``password``, ``last_login``, ``is_staff`` and ``is_superuser`` on top of
    the schema columns. Employees log in with ``email``.
    """

    employee_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee_number = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=255, unique=True)
    job_role = models.CharField(max_length=100)
    department = models.CharField(max_length=100, null=True, blank=True)
    location = models.CharField(max_length=100, null=True, blank=True)
    # Self references. Column names match the schema: manager_employee_id / buddy_employee_id
    manager_employee = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )
    buddy_employee = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="buddy_assignees"
    )
    employment_type = models.CharField(max_length=20, choices=EmploymentType.choices)
    contracted_weekly_hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    maternity_return_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # auth-only column
    is_staff = models.BooleanField(default=False, help_text="Can access admin and manage all data.")

    objects = EmployeeManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["employee_number", "first_name", "last_name"]

    class Meta:
        db_table = "employee"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["manager_employee"]),
            models.Index(fields=["buddy_employee"]),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.employee_number})"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()
