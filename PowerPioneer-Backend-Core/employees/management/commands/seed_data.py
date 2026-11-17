"""
Populate the local database with realistic demo data and score everyone.

    python manage.py seed_data            # only if the database has no employees
    python manage.py seed_data --reset    # DELETE all employees (and their data) first
"""
import random
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from employees import services as rel
from employees.models import Employee, EmploymentType
from rostering.models import (
    AbsenceType,
    Attendance,
    AttendanceStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    ShiftRoster,
    ShiftType,
)
from surveys.models import EmployeeResponse, Question, QuestionOption, QuestionSource, TriggerType
from wellbeing.services import calculate_for_all

ADMIN_EMAIL = "admin@powerpioneer.local"
ADMIN_PASSWORD = "Admin@12345"
DEFAULT_PASSWORD = "Password@123"

# (number, first, last, role, dept, location, type, weekly hours, profile)
PEOPLE = [
    ("E1001", "Jordan", "Reyes", "Ward Manager", "ICU", "North Wing", EmploymentType.FULL_TIME, 37.5, "manager"),
    ("E1002", "Sam", "Okafor", "Ward Manager", "Emergency", "South Wing", EmploymentType.FULL_TIME, 37.5, "manager"),
    ("E1003", "Taylor", "Nguyen", "Staff Nurse", "ICU", "North Wing", EmploymentType.FULL_TIME, 37.5, "healthy"),
    ("E1004", "Casey", "Patel", "Staff Nurse", "ICU", "North Wing", EmploymentType.FULL_TIME, 37.5, "overworked"),
    ("E1005", "Riley", "Kowalski", "Senior Nurse", "ICU", "North Wing", EmploymentType.FULL_TIME, 37.5, "healthy"),
    ("E1006", "Morgan", "Silva", "Staff Nurse", "ICU", "North Wing", EmploymentType.PART_TIME, 22.5, "maternity"),
    ("E1007", "Avery", "Haddad", "Staff Nurse", "Emergency", "South Wing", EmploymentType.FULL_TIME, 37.5, "strained"),
    ("E1008", "Quinn", "Larsen", "Healthcare Assistant", "Emergency", "South Wing", EmploymentType.BANK, None, "healthy"),
]


class Command(BaseCommand):
    help = "Seed demo employees, rosters, attendance, leave, surveys and wellbeing scores."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete ALL employees and related data first.")
        parser.add_argument("--days", type=int, default=60, help="Days of history to generate (default 60).")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Employee.objects.exists():
            if not opts["reset"]:
                raise CommandError("Database already has employees. Re-run with --reset to wipe and reseed.")
            Question.objects.all().delete()
            Employee.objects.all().delete()

        self.rng = random.Random(42)
        self.today = timezone.localdate()
        self.days = opts["days"]

        admin = Employee.objects.create_superuser(
            email=ADMIN_EMAIL, password=ADMIN_PASSWORD, employee_number="E0001",
            first_name="System", last_name="Admin", department="HR", location="Head Office",
            contracted_weekly_hours=Decimal("37.5"), hire_date=self.today - timedelta(days=2000),
        )

        people = {}
        for num, first, last, role, dept, loc, etype, hours, profile in PEOPLE:
            emp = Employee.objects.create_user(
                email=f"{first.lower()}.{last.lower()}@powerpioneer.local", password=DEFAULT_PASSWORD,
                employee_number=num, first_name=first, last_name=last, job_role=role, department=dept,
                location=loc, employment_type=etype,
                contracted_weekly_hours=Decimal(str(hours)) if hours else None,
                hire_date=self.today - timedelta(days=self.rng.randint(400, 3000)),
                maternity_return_date=self.today - timedelta(days=40) if profile == "maternity" else None,
            )
            people[num] = (emp, profile)

        # reporting lines & buddies through the business rules
        icu_mgr, ed_mgr = people["E1001"][0], people["E1002"][0]
        for num in ("E1003", "E1004", "E1005", "E1006"):
            rel.assign_manager(people[num][0], icu_mgr, performed_by=admin)
        for num in ("E1007", "E1008"):
            rel.assign_manager(people[num][0], ed_mgr, performed_by=admin)
        rel.assign_buddy(people["E1006"][0], people["E1005"][0], performed_by=admin)
        rel.assign_buddy(people["E1007"][0], people["E1008"][0], performed_by=admin)

        for emp, profile in people.values():
            self._shifts(emp, profile)
            self._attendance(emp, profile)
            self._leave(emp, profile)

        self._surveys(people)

        predictions = calculate_for_all(self.today, performed_by=admin)

        self.stdout.write(self.style.SUCCESS("Seed data created.\n"))
        self.stdout.write(f"  Admin login : {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        self.stdout.write(f"  Other users : <first>.<last>@powerpioneer.local / {DEFAULT_PASSWORD}\n")
        for p in sorted(predictions, key=lambda p: p.risk_score, reverse=True):
            self.stdout.write(
                f"  {p.employee.full_name:<18} wellbeing={p.risk_snapshot.wellbeing_score:>6}  band={p.risk_band}"
            )

    # -----------------------------------------------------------------------
    def _dt(self, day, hour):
        return timezone.make_aware(datetime.combine(day, time(hour % 24))) + timedelta(days=hour // 24)

    def _shifts(self, emp, profile):
        rng = self.rng
        rows = []
        prev_night = False
        for offset in range(self.days, -1, -1):
            day = self.today - timedelta(days=offset)
            if profile == "overworked":
                works, night = day.weekday() != 6 or rng.random() < 0.5, offset % 9 < 5
            elif profile == "strained":
                works, night = rng.random() < 0.6, rng.random() < 0.25
            elif profile == "maternity":
                if offset > 40:
                    continue  # on maternity leave
                works, night = day.weekday() in (0, 2, 4), rng.random() < 0.2
            elif profile == "manager":
                works, night = day.weekday() < 5, False
            else:  # healthy
                works, night = day.weekday() in (0, 1, 3) or (day.weekday() == 5 and rng.random() < 0.3), False
            # A night shift ends the next morning: that day is either another night or a rest day.
            if prev_night and not night:
                works = False
            prev_night = works and night
            if not works:
                continue

            if night:
                start, length, stype = self._dt(day, 20), 12.0, ShiftType.NIGHT
            elif profile in ("overworked", "strained") and rng.random() < 0.5:
                start, length, stype = self._dt(day, 7), 12.5, ShiftType.LONG_DAY
            else:
                start, length, stype = self._dt(day, 8), 8.0, ShiftType.DAY
            stressed = profile in ("overworked", "strained")
            extra = rng.choice([0, 0.5, 1, 1.5, 2]) if stressed else rng.choice([0, 0, 0, 0.5])
            planned_staff = rng.randint(6, 10)
            actual_staff = planned_staff - (rng.randint(1, 3) if stressed and rng.random() < 0.5 else 0)
            expected_load = Decimal(str(rng.randint(10, 18)))
            load_factor = rng.uniform(1.05, 1.35) if stressed else rng.uniform(0.85, 1.05)
            rows.append(ShiftRoster(
                employee=emp, shift_start=start, shift_end=start + timedelta(hours=length),
                planned_hours=Decimal(str(length)), actual_hours=Decimal(str(length + extra)),
                shift_type=stype, location=emp.location, expected_patient_load=expected_load,
                actual_patient_load=Decimal(str(round(float(expected_load) * load_factor, 1))),
                planned_staff_count=planned_staff, actual_staff_count=actual_staff,
                understaffed_flag=actual_staff < planned_staff,
                missed_break_flag=rng.random() < (0.45 if stressed or profile == "maternity" else 0.05),
                short_notice_change_flag=rng.random() < (0.2 if stressed else 0.03),
                redeployment_flag=rng.random() < (0.1 if stressed else 0.01),
            ))
        ShiftRoster.objects.bulk_create(rows)

    def _attendance(self, emp, profile):
        rng = self.rng
        rows = []
        shift_days = {timezone.localtime(s.shift_start).date() for s in emp.shifts.all()}
        for day in sorted(shift_days):
            late = rng.choice([0, 0, 0, 5, 15, 25]) if profile in ("overworked", "strained") else 0
            rows.append(Attendance(
                employee=emp, attendance_date=day,
                attendance_status=AttendanceStatus.LATE if late else AttendanceStatus.PRESENT, late_minutes=late,
            ))
        if profile in ("overworked", "strained"):
            # three short sickness episodes in the last 90 days
            for start_offset, length in ((70, 2), (35, 1), (12, 2)):
                episode = uuid.uuid4()
                for i in range(length):
                    day = self.today - timedelta(days=start_offset - i)
                    if day in shift_days:
                        continue
                    rows.append(Attendance(
                        employee=emp, attendance_date=day, attendance_status=AttendanceStatus.ABSENT,
                        absence_type=AbsenceType.SICK, absence_episode_id=episode, notes="Seeded sickness",
                    ))
        Attendance.objects.bulk_create(rows)

    def _leave(self, emp, profile):
        now = timezone.now()
        if profile in ("healthy", "manager"):
            start = self.today - timedelta(days=self.rng.randint(20, 60))
            LeaveRequest.objects.create(
                employee=emp, leave_type=LeaveType.ANNUAL, start_date=start, end_date=start + timedelta(days=6),
                status=LeaveStatus.APPROVED, requested_at=now - timedelta(days=90), decision_at=now - timedelta(days=88),
            )
        elif profile in ("overworked", "strained"):
            for back in (50, 20):
                start = self.today + timedelta(days=10 + back)
                LeaveRequest.objects.create(
                    employee=emp, leave_type=LeaveType.ANNUAL, start_date=start, end_date=start + timedelta(days=4),
                    status=LeaveStatus.REJECTED, requested_at=now - timedelta(days=back),
                    decision_at=now - timedelta(days=back - 2),
                )
            start = self.today + timedelta(days=30)
            LeaveRequest.objects.create(
                employee=emp, leave_type=LeaveType.ANNUAL, start_date=start, end_date=start + timedelta(days=7),
                status=LeaveStatus.PENDING, requested_at=now - timedelta(days=2),
            )
        elif profile == "maternity":
            LeaveRequest.objects.create(
                employee=emp, leave_type=LeaveType.MATERNITY, start_date=self.today - timedelta(days=300),
                end_date=self.today - timedelta(days=41), status=LeaveStatus.APPROVED,
                requested_at=now - timedelta(days=400), decision_at=now - timedelta(days=395),
            )

    def _surveys(self, people):
        scale = [("Very poor", 1), ("Poor", 2), ("Okay", 3), ("Good", 4), ("Very good", 5)]
        texts = [
            "How would you rate your energy levels this week?",
            "How well supported do you feel by your team?",
            "How manageable has your workload been?",
            "How well have you been sleeping between shifts?",
        ]
        questions = []
        for text in texts:
            q = Question.objects.create(question_text=text, source=QuestionSource.MANUAL,
                                        trigger_type=TriggerType.SCHEDULED)
            opts = [QuestionOption.objects.create(question=q, option_text=t, normalized_score=s, display_order=i)
                    for i, (t, s) in enumerate(scale)]
            questions.append((q, opts))

        mood = {"healthy": (3, 4), "manager": (3, 4), "overworked": (0, 1), "strained": (1, 2), "maternity": (1, 3)}
        for emp, profile in people.values():
            lo, hi = mood[profile]
            for q, opts in questions:
                EmployeeResponse.objects.create(
                    employee=emp, question=q, option=opts[self.rng.randint(lo, hi)],
                    responded_at=timezone.now() - timedelta(days=self.rng.randint(1, 10)),
                )

        # A personalised, model-generated follow-up for the most at-risk profile
        target = people["E1004"][0]
        q = Question.objects.create(
            question_text="You have worked several night shifts in a row recently. Do you feel rested enough?",
            source=QuestionSource.AI_GENERATED, trigger_type=TriggerType.RISK_TRIGGERED,
            generated_for_employee=target, context_data={"feature": "max_consecutive_night_shifts"},
            model_name="demo-llm", prompt_version="v1", expires_at=timezone.now() + timedelta(days=7),
        )
        for i, (t, s) in enumerate([("Not at all", 1), ("Somewhat", 3), ("Yes, fully", 5)]):
            QuestionOption.objects.create(question=q, option_text=t, normalized_score=s, display_order=i)
