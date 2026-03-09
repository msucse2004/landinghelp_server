"""
Critical workflow tests: price visibility, status consistency.
Run: python manage.py test settlement.tests.test_workflow_critical
"""
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model

from settlement.constants import (
    message_may_include_price,
    can_view_price,
    quote_for_customer,
)
from settlement.models import SettlementQuote
from survey.models import SurveySubmission

User = get_user_model()


class PriceVisibilityTests(TestCase):
    """Ensure customer-facing price never exposed before FINAL_SENT."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='customer_test',
            email='customer@test.com',
            password='testpass123',
        )
        self.submission = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )

    def test_message_may_include_price_draft_false(self):
        quote = SettlementQuote(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('100'),
            items=[{'code': 'X', 'label': 'Y', 'price': 100}],
        )
        self.assertFalse(message_may_include_price(quote))
        self.assertFalse(message_may_include_price(SettlementQuote.Status.DRAFT))

    def test_message_may_include_price_negotiating_false(self):
        self.assertFalse(message_may_include_price(SettlementQuote.Status.NEGOTIATING))

    def test_message_may_include_price_final_sent_true(self):
        quote = SettlementQuote(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
        )
        self.assertTrue(message_may_include_price(quote))
        self.assertTrue(message_may_include_price(SettlementQuote.Status.FINAL_SENT))

    def test_message_may_include_price_paid_true(self):
        self.assertTrue(message_may_include_price(SettlementQuote.Status.PAID))

    def test_message_may_include_price_none_false(self):
        self.assertFalse(message_may_include_price(None))

    def test_can_view_price_none_quote_false(self):
        self.assertFalse(can_view_price(self.user, None))

    def test_can_view_price_draft_false(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('0'),
            items=[],
        )
        self.assertFalse(can_view_price(self.user, quote))

    def test_can_view_price_final_sent_true(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
            items=[{'code': 'X', 'label': 'Y', 'price': 100}],
        )
        self.assertTrue(can_view_price(self.user, quote))

    def test_quote_for_customer_masks_price_when_draft(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('200'),
            items=[
                {'code': 'A', 'label': 'Service A', 'price': 100},
                {'code': 'B', 'label': 'Service B', 'price': 100},
            ],
        )
        out = quote_for_customer(quote)
        self.assertIsNotNone(out)
        self.assertIsNone(out['total'])
        for item in out['items']:
            self.assertNotIn('price', item)
            self.assertTrue(item.get('_masked'))

    def test_quote_for_customer_shows_price_when_final_sent(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('200'),
            items=[
                {'code': 'A', 'label': 'Service A', 'price': 100},
            ],
        )
        out = quote_for_customer(quote)
        self.assertIsNotNone(out)
        self.assertEqual(out['total'], 200)
        for item in out['items']:
            self.assertFalse(item.get('_masked', False))
            self.assertIn('price', item)
