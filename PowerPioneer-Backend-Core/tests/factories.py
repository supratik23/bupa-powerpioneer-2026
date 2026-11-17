import itertools
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from employees.models import Employee, EmploymentType
from rostering.models import ShiftRoster, ShiftType

_seq = itertools.count(1)
PASSWORD = "S3cure-pass!"


def make_employee(**kwargs) -> Employee:
    n = next(_seq)
    defaults = dict(
        email=f"user{n}@test.local", password=PASSWORD, employee_number=f"T{n:04d}",
        first_name=f"First{n}", last_name=f"Last{n}", job_role="Staff Nurse", department="ICU",
        location="North", employment_type=EmploymentType.FULL_TIME, contracted_weekly_hours=Decimal("37.5"),
    )
    defaults.update(kwargs)
    return Employee.objects.create_user(**defaults)


def make_staff(**kwargs) -> Employee:
    return make_employee(is_staff=True, **kwargs)


def make_shift(employee, day, start_hour=8, hours=8.0, shift_type=ShiftType.DAY, **kwargs) -> ShiftRoster:
    start = timezone.make_aware(datetime.combine(day, time(start_hour)))
    return ShiftRoster.objects.create(
        employee=employee, shift_start=start, shift_end=start + timedelta(hours=hours),
        planned_hours=Decimal(str(hours)), shift_type=shift_type, **kwargs,
    )
