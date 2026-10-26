# apps/accounts/tests.py
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

User = get_user_model()
PASSWORD = "S3curePass!x"


class AuthFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", PASSWORD)

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(
            resp,
            f"{reverse('accounts:login')}?next={reverse('core:dashboard')}",
            fetch_redirect_response=False,
        )

    def test_login_with_email(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "owner@example.com", "password": PASSWORD})
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)

    def test_bad_password_shows_error(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "owner@example.com", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["form"].errors)

    def test_reset_email_sent_only_for_known_address(self):
        for address, expected in (("owner@example.com", 1), ("nobody@example.com", 0)):
            mail.outbox.clear()
            resp = self.client.post(reverse("accounts:password_reset"), {"email": address})
            self.assertRedirects(resp, reverse("accounts:password_reset_done"), fetch_redirect_response=False)
            self.assertEqual(len(mail.outbox), expected)

    def test_reset_link_sets_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        resp = self.client.get(url, follow=True)  # Django swaps the token for a session-backed URL
        post_url = resp.redirect_chain[-1][0]
        new = "An0ther!Pass99"
        resp = self.client.post(post_url, {"new_password1": new, "new_password2": new})
        self.assertRedirects(resp, reverse("accounts:password_reset_complete"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))