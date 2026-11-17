import uuid
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from rostering.models import AbsenceType, Attendance, AttendanceStatus, LeaveRequest, LeaveStatus, ShiftType
from surveys.models import EmployeeResponse, Question, QuestionOption
from wellbeing.features import extract_features
from wellbeing.models import EmployeeRiskSnapshot, Intervention, RiskPrediction
from wellbeing.scoring import band_for, calculate_score

from .factories import make_employee, make_shift, make_staff


class FeatureExtractionTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.emp = make_employee(contracted_weekly_hours=Decimal("35"))

    def test_shift_patterns(self):
        # 4 consecutive nights ending 3 days ago, then a day shift with short rest
        for i in range(4):
            make_shift(self.emp, self.today - timedelta(days=6 - i), start_hour=20, hours=12,
                       shift_type=ShiftType.NIGHT, missed_break_flag=True)
        # previous night ends at 08:00 on (today-2); this shift starts 14:00 the same day => 6h rest
        make_shift(self.emp, self.today - timedelta(days=2), start_hour=14, hours=8,
                   short_notice_change_flag=True, planned_staff_count=8, actual_staff_count=6)
        c = extract_features(self.emp, self.today).columns
        self.assertEqual(c["night_shifts_30d"], 4)
        self.assertEqual(c["max_consecutive_night_shifts"], 4)
        self.assertEqual(c["max_consecutive_work_days"], 5)
        self.assertEqual(c["long_shifts_30d"], 4)
        self.assertEqual(c["minimum_rest_hours_between_shifts"], Decimal("6"))
        self.assertEqual(c["missed_breaks_30d"], 4)
        self.assertEqual(c["short_notice_roster_changes_30d"], 1)
        self.assertEqual(c["understaffed_shift_ratio_30d"], Decimal("0.2"))
        self.assertEqual(c["actual_hours_worked_30d"], Decimal("56"))
        self.assertEqual(c["contracted_hours_30d"], Decimal("150"))

    def test_absence_episodes_and_late_arrivals(self):
        episode = uuid.uuid4()
        for i in range(3):
            Attendance.objects.create(employee=self.emp, attendance_date=self.today - timedelta(days=40 + i),
                                      attendance_status=AttendanceStatus.ABSENT, absence_type=AbsenceType.SICK,
                                      absence_episode_id=episode)
        # two separate loose single-day absences
        for d in (10, 20):
            Attendance.objects.create(employee=self.emp, attendance_date=self.today - timedelta(days=d),
                                      attendance_status=AttendanceStatus.ABSENT, absence_type=AbsenceType.UNPLANNED)
        # planned absence does not count
        Attendance.objects.create(employee=self.emp, attendance_date=self.today - timedelta(days=5),
                                  attendance_status=AttendanceStatus.ABSENT, absence_type=AbsenceType.PLANNED)
        Attendance.objects.create(employee=self.emp, attendance_date=self.today - timedelta(days=1),
                                  attendance_status=AttendanceStatus.LATE, late_minutes=12)
        c = extract_features(self.emp, self.today).columns
        self.assertEqual(c["unplanned_absence_days_90d"], 5)
        self.assertEqual(c["unplanned_absence_episodes_90d"], 3)
        self.assertEqual(c["late_arrivals_30d"], 1)

    def test_leave_features(self):
        now = timezone.now()
        LeaveRequest.objects.create(employee=self.emp, leave_type="ANNUAL", status=LeaveStatus.APPROVED,
                                    start_date=self.today - timedelta(days=50), end_date=self.today - timedelta(days=44),
                                    requested_at=now - timedelta(days=100))
        LeaveRequest.objects.create(employee=self.emp, leave_type="ANNUAL", status=LeaveStatus.REJECTED,
                                    start_date=self.today + timedelta(days=5), end_date=self.today + timedelta(days=9),
                                    requested_at=now - timedelta(days=3))
        c = extract_features(self.emp, self.today).columns
        self.assertEqual(c["days_since_last_meaningful_leave"], 44)
        self.assertEqual(c["cancelled_or_rejected_leave_90d"], 1)

    def test_maternity_return_features(self):
        self.emp.maternity_return_date = self.today - timedelta(days=20)
        self.emp.save()
        make_shift(self.emp, self.today - timedelta(days=10), hours=8, actual_hours=Decimal("10"))
        make_shift(self.emp, self.today - timedelta(days=8), start_hour=20, hours=12, shift_type=ShiftType.NIGHT,
                   missed_break_flag=True)
        c = extract_features(self.emp, self.today).columns
        self.assertEqual(c["days_since_maternity_return"], 20)
        self.assertEqual(c["overtime_hours_since_maternity_return"], Decimal("2"))
        self.assertEqual(c["maternity_adjustments_fulfilment_ratio"], Decimal("0.5"))
        self.assertEqual(c["nursing_or_recovery_breaks_missed_30d"], 1)

    def test_survey_scores_normalised_per_question(self):
        q = Question.objects.create(question_text="Energy?")
        low = QuestionOption.objects.create(question=q, option_text="low", normalized_score=1)
        QuestionOption.objects.create(question=q, option_text="high", normalized_score=5)
        EmployeeResponse.objects.create(employee=self.emp, question=q, option=low)
        fs = extract_features(self.emp, self.today)
        self.assertEqual(fs.survey_score, 0.0)
        self.assertEqual(fs.survey_responses, 1)


class ScoringTests(APITestCase):
    def test_clean_record_scores_100(self):
        result = calculate_score({"overtime_ratio_30d": 0, "night_shifts_30d": 0})
        self.assertEqual(result.wellbeing_score, 100)
        self.assertEqual(result.risk_band, "LOW")
        self.assertEqual(result.contributions, [])

    def test_penalties_are_capped_and_survey_adjusts(self):
        result = calculate_score({"overtime_ratio_30d": 5, "missed_breaks_30d": 3}, survey_score=1.0)
        by_name = {c.feature_name: c.points for c in result.contributions}
        self.assertEqual(by_name["overtime_ratio_30d"], 15)       # capped
        self.assertEqual(by_name["missed_breaks_30d"], 2)
        self.assertEqual(by_name["survey_sentiment_30d"], -10)    # protective
        self.assertEqual(result.wellbeing_score, 93)

    def test_bands(self):
        self.assertEqual(band_for(80), "LOW")
        self.assertEqual(band_for(60), "MODERATE")
        self.assertEqual(band_for(40), "HIGH")
        self.assertEqual(band_for(10), "CRITICAL")


class WellbeingApiTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.manager = make_employee()
        self.emp = make_employee(manager_employee=self.manager, contracted_weekly_hours=Decimal("20"))
        self.stranger = make_employee()
        # heavy month: 20 x 13h night shifts with missed breaks, understaffed
        for i in range(20):
            make_shift(self.emp, self.today - timedelta(days=i), start_hour=19, hours=13,
                       shift_type=ShiftType.NIGHT, missed_break_flag=True, understaffed_flag=True,
                       short_notice_change_flag=i % 3 == 0)

    def test_calculate_creates_snapshot_prediction_explanations_and_interventions(self):
        self.client.force_authenticate(self.manager)
        res = self.client.post("/api/wellbeing/calculate/", {"employee_id": str(self.emp.pk)}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIn(res.data["prediction"]["risk_band"], ("HIGH", "CRITICAL"))
        self.assertTrue(res.data["prediction"]["explanations"])
        self.assertEqual(EmployeeRiskSnapshot.objects.filter(employee=self.emp).count(), 1)
        types = set(Intervention.objects.filter(employee=self.emp).values_list("action_type", flat=True))
        self.assertIn("NOTIFY_MANAGER", types)
        self.assertIn("SUGGEST_BUDDY", types)

        # recalculating the same day updates the snapshot and does not duplicate pending interventions
        self.client.post("/api/wellbeing/calculate/", {"employee_id": str(self.emp.pk)}, format="json")
        self.assertEqual(EmployeeRiskSnapshot.objects.filter(employee=self.emp).count(), 1)
        self.assertEqual(RiskPrediction.objects.filter(employee=self.emp).count(), 2)
        self.assertEqual(Intervention.objects.filter(employee=self.emp, action_type="NOTIFY_MANAGER").count(), 1)

        summary = self.client.get(f"/api/wellbeing/employees/{self.emp.pk}/")
        self.assertEqual(summary.status_code, 200)
        self.assertIsNotNone(summary.data["latest_wellbeing_score"])
        team = self.client.get("/api/wellbeing/team/")
        self.assertEqual([t["employee_id"] for t in team.data], [str(self.emp.pk)])

    def test_unrelated_employee_cannot_calculate_or_view(self):
        self.client.force_authenticate(self.stranger)
        res = self.client.post("/api/wellbeing/calculate/", {"employee_id": str(self.emp.pk)}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.client.get(f"/api/wellbeing/employees/{self.emp.pk}/").status_code, 403)
        # scoped list: stranger sees none of emp's shifts
        self.assertEqual(self.client.get("/api/shifts/").data["count"], 0)

    def test_calculate_all_is_staff_only(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post("/api/wellbeing/calculate-all/", {}, format="json").status_code, 403)
        self.client.force_authenticate(make_staff())
        res = self.client.post("/api/wellbeing/calculate-all/", {"create_interventions": False}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["employees_scored"], 4)
