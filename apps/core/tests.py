# apps/core/tests.py
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class WorkspaceSwitchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        User.objects.create_user("owner@example.com", "S3curePass!x")
        self.client.login(username="owner@example.com", password="S3curePass!x")

    def test_switch_is_stored_in_session(self):
        self.client.post(reverse("core:switch_workspace"), {"workspace": "work"})
        self.assertEqual(self.client.session["active_workspace"], "work")

    def test_invalid_workspace_is_ignored(self):
        self.client.post(reverse("core:switch_workspace"), {"workspace": "bogus"})
        self.assertNotIn("active_workspace", self.client.session)

    def test_external_next_url_is_rejected(self):
        resp = self.client.post(
            reverse("core:switch_workspace"), {"workspace": "work", "next": "https://evil.example/"}
        )
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)