from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from surveys.models import Question, QuestionOption

from .factories import make_employee, make_staff


class ShiftCrudTests(APITestCase):
    def setUp(self):
        self.manager = make_employee()
        self.emp = make_employee(manager_employee=self.manager)

    def test_manager_crud_and_defaults(self):
        self.client.force_authenticate(self.manager)
        start = timezone.now().replace(microsecond=0)
        res = self.client.post("/api/shifts/", {
            "employee_id": str(self.emp.pk), "shift_start": start.isoformat(),
            "shift_end": (start + timedelta(hours=7.5)).isoformat(), "shift_type": "DAY",
            "planned_staff_count": 6, "actual_staff_count": 5,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["planned_hours"], 7.5)
        self.assertTrue(res.data["understaffed_flag"])
        sid = res.data["shift_id"]
        self.assertEqual(self.client.patch(f"/api/shifts/{sid}/", {"actual_hours": 9}, format="json").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/shifts/{sid}/").status_code, 204)

    def test_employee_cannot_write_own_shift_and_end_must_follow_start(self):
        self.client.force_authenticate(self.emp)
        start = timezone.now()
        body = {"employee_id": str(self.emp.pk), "shift_start": start.isoformat(),
                "shift_end": (start + timedelta(hours=8)).isoformat(), "shift_type": "DAY"}
        self.assertEqual(self.client.post("/api/shifts/", body, format="json").status_code, 403)
        self.client.force_authenticate(self.manager)
        body["shift_end"] = (start - timedelta(hours=1)).isoformat()
        self.assertEqual(self.client.post("/api/shifts/", body, format="json").status_code, 400)


class LeaveWorkflowTests(APITestCase):
    def setUp(self):
        self.manager = make_employee()
        self.emp = make_employee(manager_employee=self.manager)
        self.today = timezone.localdate()

    def test_employee_requests_manager_approves(self):
        self.client.force_authenticate(self.emp)
        res = self.client.post("/api/leave-requests/", {
            "leave_type": "ANNUAL", "start_date": str(self.today + timedelta(days=10)),
            "end_date": str(self.today + timedelta(days=14)),
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["status"], "PENDING")
        lid = res.data["leave_request_id"]

        self.assertEqual(self.client.post(f"/api/leave-requests/{lid}/approve/").status_code, 403)
        overlap = self.client.post("/api/leave-requests/", {
            "leave_type": "ANNUAL", "start_date": str(self.today + timedelta(days=12)),
            "end_date": str(self.today + timedelta(days=20)),
        }, format="json")
        self.assertEqual(overlap.status_code, 400)

        self.client.force_authenticate(self.manager)
        res = self.client.post(f"/api/leave-requests/{lid}/approve/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "APPROVED")
        self.assertIsNotNone(res.data["decision_at"])
        self.assertEqual(self.client.post(f"/api/leave-requests/{lid}/reject/").status_code, 400)


class AttendanceValidationTests(APITestCase):
    def test_absent_requires_absence_type(self):
        staff = make_staff()
        emp = make_employee()
        self.client.force_authenticate(staff)
        body = {"employee_id": str(emp.pk), "attendance_date": str(timezone.localdate()),
                "attendance_status": "ABSENT", "late_minutes": 0}
        self.assertEqual(self.client.post("/api/attendance/", body, format="json").status_code, 400)
        body["absence_type"] = "SICK"
        self.assertEqual(self.client.post("/api/attendance/", body, format="json").status_code, 201)


class SurveyTests(APITestCase):
    def setUp(self):
        self.staff = make_staff()
        self.emp = make_employee()

    def test_staff_creates_question_with_options_and_employee_answers(self):
        self.client.force_authenticate(self.staff)
        res = self.client.post("/api/questions/", {
            "question_text": "How are you?", "source": "MANUAL", "trigger_type": "SCHEDULED",
            "options": [{"option_text": "Bad", "normalized_score": 0}, {"option_text": "Good", "normalized_score": 100}],
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        qid, good = res.data["question_id"], res.data["options"][1]["option_id"]

        self.client.force_authenticate(self.emp)
        self.assertEqual(self.client.post("/api/questions/", {"question_text": "x"}, format="json").status_code, 403)
        pending = self.client.get("/api/questions/pending/")
        self.assertEqual(pending.data["count"], 1)
        res = self.client.post(f"/api/questions/{qid}/answer/", {"option_id": good}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(self.client.get("/api/questions/pending/").data["count"], 0)

    def test_option_must_belong_to_question(self):
        q1 = Question.objects.create(question_text="A")
        q2 = Question.objects.create(question_text="B")
        opt = QuestionOption.objects.create(question=q2, option_text="x", normalized_score=1)
        self.client.force_authenticate(self.emp)
        res = self.client.post("/api/employee-responses/", {"question_id": str(q1.pk), "option_id": str(opt.pk)},
                               format="json")
        self.assertEqual(res.status_code, 400)

    def test_personal_questions_hidden_from_others(self):
        other = make_employee()
        Question.objects.create(question_text="Just for other", generated_for_employee=other)
        self.client.force_authenticate(self.emp)
        self.assertEqual(self.client.get("/api/questions/").data["count"], 0)


class InterventionTests(APITestCase):
    def test_target_can_complete(self):
        manager = make_employee()
        emp = make_employee(manager_employee=manager)
        self.client.force_authenticate(manager)
        res = self.client.post("/api/interventions/", {
            "employee_id": str(emp.pk), "target_employee_id": str(manager.pk),
            "action_type": "SCHEDULE_CHECKIN", "action_status": "PENDING",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        iid = res.data["intervention_id"]
        res = self.client.post(f"/api/interventions/{iid}/complete/")
        self.assertEqual(res.data["action_status"], "COMPLETED")
        self.assertIsNotNone(res.data["completed_at"])
        self.assertEqual(self.client.post(f"/api/interventions/{iid}/start/").status_code, 400)
