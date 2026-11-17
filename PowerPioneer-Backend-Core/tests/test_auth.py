from rest_framework.test import APITestCase

from .factories import PASSWORD, make_employee


class AuthTests(APITestCase):
    def setUp(self):
        self.emp = make_employee()

    def login(self):
        return self.client.post("/api/auth/token/", {"email": self.emp.email, "password": PASSWORD}, format="json")

    def test_obtain_refresh_and_me(self):
        res = self.login()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn("access", res.data)
        self.assertEqual(res.data["employee"]["employee_id"], str(self.emp.pk))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["email"], self.emp.email)

        refreshed = self.client.post("/api/auth/token/refresh/", {"refresh": res.data["refresh"]}, format="json")
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("access", refreshed.data)

    def test_logout_blacklists_refresh_token(self):
        tokens = self.login().data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.post("/api/auth/logout/", {"refresh": tokens["refresh"]}, format="json")
                         .status_code, 200)
        again = self.client.post("/api/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_wrong_password_and_anonymous_access(self):
        bad = self.client.post("/api/auth/token/", {"email": self.emp.email, "password": "nope"}, format="json")
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(self.client.get("/api/employees/").status_code, 401)

    def test_register_creates_non_staff_employee(self):
        res = self.client.post("/api/auth/register/", {
            "employee_number": "R1", "first_name": "New", "last_name": "Hire", "email": "new@test.local",
            "password": "An0ther-secure", "job_role": "Nurse", "employment_type": "FULL_TIME",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertNotIn("password", res.data)

    def test_swagger_schema_is_served(self):
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
