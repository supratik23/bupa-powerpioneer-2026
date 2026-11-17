from django.test import override_settings
from rest_framework.test import APITestCase

from wellbeing.models import Intervention

from .factories import make_employee, make_staff


class ManagerAssignmentTests(APITestCase):
    def setUp(self):
        self.staff = make_staff()
        self.boss = make_employee()
        self.lead = make_employee()
        self.nurse = make_employee()
        self.client.force_authenticate(self.staff)

    def assign_manager(self, emp, mgr):
        return self.client.post(f"/api/employees/{emp.pk}/assign-manager/",
                                {"manager_employee_id": str(mgr.pk)}, format="json")

    def test_assign_and_remove_manager_logs_interventions(self):
        res = self.assign_manager(self.nurse, self.lead)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["manager_employee_id"], self.lead.pk)
        self.assertTrue(Intervention.objects.filter(employee=self.nurse, action_type="ASSIGN_MANAGER").exists())

        res = self.client.post(f"/api/employees/{self.nurse.pk}/remove-manager/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["manager_employee_id"])
        self.assertTrue(Intervention.objects.filter(employee=self.nurse, action_type="REMOVE_MANAGER").exists())

    def test_cannot_manage_self(self):
        self.assertEqual(self.assign_manager(self.nurse, self.nurse).status_code, 400)

    def test_cycle_is_rejected(self):
        self.assign_manager(self.lead, self.boss)
        self.assign_manager(self.nurse, self.lead)
        res = self.assign_manager(self.boss, self.nurse)  # boss -> nurse -> lead -> boss
        self.assertEqual(res.status_code, 400)
        self.assertIn("cycle", str(res.data))

    def test_inactive_manager_rejected(self):
        self.lead.is_active = False
        self.lead.save()
        self.assertEqual(self.assign_manager(self.nurse, self.lead).status_code, 400)

    def test_only_staff_assign_managers(self):
        self.client.force_authenticate(self.boss)
        self.assertEqual(self.assign_manager(self.nurse, self.boss).status_code, 403)

    def test_create_with_manager_goes_through_rules(self):
        res = self.client.post("/api/employees/", {
            "employee_number": "X1", "first_name": "A", "last_name": "B", "email": "x1@test.local",
            "job_role": "Nurse", "employment_type": "FULL_TIME", "manager_employee_id": str(self.boss.pk),
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["manager_employee_id"], self.boss.pk)

    def test_deactivate_reassigns_reports_and_clears_buddies(self):
        self.assign_manager(self.lead, self.boss)
        self.assign_manager(self.nurse, self.lead)
        peer = make_employee()
        self.client.post(f"/api/employees/{peer.pk}/assign-buddy/", {"buddy_employee_id": str(self.lead.pk)},
                         format="json")
        res = self.client.post(f"/api/employees/{self.lead.pk}/deactivate/")
        self.assertEqual(res.status_code, 200, res.data)
        self.nurse.refresh_from_db()
        peer.refresh_from_db()
        self.assertEqual(self.nurse.manager_employee_id, self.boss.pk)
        self.assertIsNone(peer.buddy_employee_id)


class BuddyAssignmentTests(APITestCase):
    def setUp(self):
        self.staff = make_staff()
        self.manager = make_employee()
        self.nurse = make_employee(manager_employee=self.manager)
        self.peer = make_employee(manager_employee=self.manager)

    def assign_buddy(self, emp, buddy):
        return self.client.post(f"/api/employees/{emp.pk}/assign-buddy/",
                                {"buddy_employee_id": str(buddy.pk)}, format="json")

    def test_manager_can_assign_buddy_to_own_report(self):
        self.client.force_authenticate(self.manager)
        res = self.assign_buddy(self.nurse, self.peer)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["buddy_employee_id"], self.peer.pk)
        res = self.client.post(f"/api/employees/{self.nurse.pk}/remove-buddy/", {"reason": "done"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["buddy_employee_id"])

    def test_unrelated_employee_cannot_assign_buddy(self):
        self.client.force_authenticate(self.peer)
        self.assertEqual(self.assign_buddy(self.nurse, self.peer).status_code, 403)

    def test_manager_cannot_be_buddy_and_vice_versa(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.assign_buddy(self.nurse, self.manager).status_code, 400)
        self.assertEqual(self.assign_buddy(self.manager, self.nurse).status_code, 400)
        self.assertEqual(self.assign_buddy(self.nurse, self.nurse).status_code, 400)

    @override_settings(BUDDY_MAX_ASSIGNEES=1)
    def test_buddy_capacity_enforced(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.assign_buddy(self.nurse, self.peer).status_code, 200)
        other = make_employee()
        res = self.assign_buddy(other, self.peer)
        self.assertEqual(res.status_code, 400)
        self.assertIn("maximum", str(res.data))

    def test_suggestions_prefer_same_department_and_exclude_manager(self):
        self.client.force_authenticate(self.staff)
        make_employee(department="Radiology", location="South")
        res = self.client.get(f"/api/employees/{self.nurse.pk}/suggest-buddies/")
        self.assertEqual(res.status_code, 200)
        ids = [s["employee_id"] for s in res.data]
        self.assertNotIn(str(self.manager.pk), ids)
        self.assertNotIn(str(self.nurse.pk), ids)
        self.assertEqual(res.data[0]["department"], "ICU")
