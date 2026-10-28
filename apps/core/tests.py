# apps/core/tests.py
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal
from .models import Transaction

User = get_user_model()
PASSWORD = "S3curePass!x"


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

class WorkspaceSeedTests(TestCase):
    def test_new_user_gets_workspaces_and_default_categories(self):
        user = User.objects.create_user("a@example.com", PASSWORD)
        self.assertEqual(user.workspaces.count(), 2)
        household = user.workspaces.get(type="household")
        self.assertTrue(household.categories.filter(name="Family support").exists())


class TransactionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner@example.com", PASSWORD)
        self.client.force_login(self.user)
        self.ws = self.user.workspaces.get(type="household")
        self.groceries = self.ws.categories.get(name="Groceries")
        self.salary = self.ws.categories.get(name="Salary")

    def test_direction_follows_category_kind(self):
        out = Transaction.objects.create(workspace=self.ws, category=self.groceries, amount=Decimal("10"), currency="USD")
        inc = Transaction.objects.create(workspace=self.ws, category=self.salary, amount=Decimal("10"), currency="USD")
        self.assertEqual((out.direction, inc.direction), ("out", "in"))

    def test_base_amount_uses_rate(self):
        t = Transaction.objects.create(
            workspace=self.ws, category=self.groceries, amount=Decimal("1290.00"),
            currency="KES", rate_to_base=Decimal("0.00775194"),
        )
        self.assertEqual(t.base_amount, Decimal("10.00"))

    def _post(self, **extra):
        data = {"category": self.groceries.pk, "amount": "25.50", "currency": "USD",
                "date": "2026-10-20", "payment_method": "cash", "note": "Milk"}
        data.update(extra)
        return self.client.post(reverse("core:transaction_create"), data)

    def test_create_in_workspace_currency(self):
        resp = self._post()
        self.assertRedirects(resp, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertEqual(Transaction.objects.get().rate_to_base, Decimal("1"))

    def test_foreign_currency_requires_rate(self):
        resp = self._post(currency="KES")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("exchange_rate", resp.context["form"].errors)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_foreign_currency_stores_inverse_rate(self):
        self._post(currency="KES", amount="1290", exchange_rate="129")
        t = Transaction.objects.get()
        self.assertEqual(t.rate_to_base, Decimal("0.00775194"))
        self.assertEqual(t.base_amount, Decimal("10.00"))

    def test_cannot_use_another_workspaces_category(self):
        other = User.objects.create_user("other@example.com", PASSWORD)
        foreign = other.workspaces.get(type="household").categories.get(name="Groceries")
        resp = self._post(category=foreign.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)