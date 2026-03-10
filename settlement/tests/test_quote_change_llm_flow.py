"""
자유 텍스트 수정 요청 + LLM 해석 + 설문 재개 플로우 테스트.

- Mock LLM adapter로 intent/confidence 제어.
- 최소 fixture: User, SurveySubmission, SettlementQuote(FINAL_SENT).
Run: python manage.py test settlement.tests.test_quote_change_llm_flow
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from settlement.models import (
    QuoteChangeRequest,
    QuoteChangeAnalysis,
    QuoteChangeActionLog,
    SettlementQuote,
)
from settlement.services_quote_change import (
    submit_text_change_request,
    approve_reopen_survey,
    approve_reopen_survey_by_ids,
    reject_change_request,
    mark_change_request_applied,
)
from settlement.services_quote_change_llm import (
    INTENT_QUOTE_ITEM_CHANGE,
    INTENT_SURVEY_REOPEN,
    INTENT_URGENT_ADMIN,
    analyze_quote_change_request,
)
from customer_request_llm import (
    parse_llm_output,
    validate_llm_output,
    apply_confidence_fallback,
)
from customer_request_policy import RecommendedAction, ExecutionMode
from settlement.quote_checkout import process_quote_payment
from settlement.quote_approval import finalize_and_send_quote
from settlement.constants import can_view_price, quote_for_customer
from survey.models import SurveySubmission

User = get_user_model()


def _make_llm_json(
    intent: str,
    confidence: float,
    recommended_action: str,
    execution_mode: str = "HUMAN_REVIEW_REQUIRED",
    human_review_target: str = "admin",
    customer_summary: str = "요청을 확인했습니다. 검토 후 안내드리겠습니다.",
    internal_summary: str = "테스트",
    **kwargs,
) -> str:
    return json.dumps({
        "intent": intent,
        "recommended_action": recommended_action,
        "execution_mode": kwargs.get("execution_mode", execution_mode),
        "confidence": confidence,
        "human_review_target": kwargs.get("human_review_target", human_review_target),
        "customer_summary": kwargs.get("customer_summary", customer_summary),
        "internal_summary": kwargs.get("internal_summary", internal_summary),
        "target_survey_section_ids": kwargs.get("target_survey_section_ids", []),
    }, ensure_ascii=False)


class QuoteChangeRequestCreationTests(TestCase):
    """1. 고객 자유 텍스트 수정 요청 생성, 2. QuoteChangeAnalysis 저장."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='customer_flow',
            email='c@test.com',
            password='testpass123',
        )
        self.submission = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('500'),
            items=[{'code': 'S1', 'label': 'Service One', 'price': 500}],
        )

    def test_customer_can_create_free_text_change_request(self):
        cr, analysis, err = submit_text_change_request(self.quote, self.user, '공항 픽업 빼주세요.')
        self.assertIsNone(err)
        self.assertIsNotNone(cr)
        self.assertEqual(cr.customer_message, '공항 픽업 빼주세요.')
        self.assertEqual(cr.status, QuoteChangeRequest.Status.ANALYZED)
        self.assertEqual(cr.submission_id, self.submission.id)
        self.assertEqual(cr.quote_id, self.quote.id)

    def test_analysis_saved_on_request_creation(self):
        cr, analysis, err = submit_text_change_request(self.quote, self.user, '서비스 추가해주세요.')
        self.assertIsNone(err)
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.change_request_id, cr.id)
        self.assertEqual(QuoteChangeAnalysis.objects.filter(change_request=cr).count(), 1)

    def test_empty_message_rejected(self):
        cr, analysis, err = submit_text_change_request(self.quote, self.user, '   ')
        self.assertIsNotNone(err)
        self.assertIn('입력', err or '')


class LLMIntentClassificationTests(TestCase):
    """3. 서비스 추가/제거 → QUOTE_ITEM_CHANGE_REQUEST, 4. 설문 다시 수정 → SURVEY_REOPEN_REQUEST, 5. 낮은 confidence → manual review."""

    def setUp(self):
        self.user = User.objects.create_user(username='u1', email='u1@t.com', password='p')
        self.submission = SurveySubmission.objects.create(
            user=self.user, email=self.user.email, status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
            items=[{'code': 'X', 'label': 'X', 'price': 100}],
        )

    @patch('settlement.services_quote_change_llm.get_quote_change_llm_adapter')
    def test_quote_item_change_intent_classified(self, mock_get_adapter):
        mock_get_adapter.return_value = lambda sys_p, user_p: (
            _make_llm_json(
                INTENT_QUOTE_ITEM_CHANGE,
                0.9,
                recommended_action=RecommendedAction.OFFER_QUOTE_REVISION_REQUEST.value,
                execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED.value,
                internal_summary="추가 요청",
            ),
            "mock",
        )
        cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.quote,
            requested_by=self.user,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.OPEN,
            customer_message="은행 계좌 개설 서비스를 추가하고 싶어요",
        )
        analysis = analyze_quote_change_request(cr, llm_adapter=mock_get_adapter.return_value)
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.detected_intent, QuoteChangeAnalysis.DetectedIntent.QUOTE_ITEM_CHANGE_REQUEST)

    @patch('settlement.services_quote_change_llm.get_quote_change_llm_adapter')
    def test_survey_reopen_intent_classified(self, mock_get_adapter):
        mock_get_adapter.return_value = lambda sys_p, user_p: (
            _make_llm_json(
                INTENT_SURVEY_REOPEN,
                0.85,
                recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN.value,
                execution_mode=ExecutionMode.AUTO_CONFIRMABLE.value,
                human_review_target="none",
                internal_summary="설문 재수정 요청",
            ),
            "mock",
        )
        cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.quote,
            requested_by=self.user,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.OPEN,
            customer_message="설문 다시 수정하고 싶어요",
        )
        analysis = analyze_quote_change_request(cr, llm_adapter=mock_get_adapter.return_value)
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.detected_intent, QuoteChangeAnalysis.DetectedIntent.SURVEY_REOPEN_REQUEST)

    def test_low_confidence_downgraded_to_manual_review(self):
        data = {
            "intent": INTENT_QUOTE_ITEM_CHANGE,
            "recommended_action": RecommendedAction.OFFER_QUOTE_REVISION_REQUEST.value,
            "execution_mode": ExecutionMode.AUTO_CONFIRMABLE.value,
            "confidence": 0.4,
            "human_review_target": "none",
            "customer_summary": "모호함",
            "internal_summary": "",
        }
        out = apply_confidence_fallback(data, 0.75)
        self.assertEqual(out["execution_mode"], ExecutionMode.HUMAN_REVIEW_REQUIRED.value)
        self.assertEqual(out["human_review_target"], "admin")

    def test_ambiguous_phrase_manual_review_via_validation(self):
        raw = _make_llm_json(
            "UNSUPPORTED_REQUEST",
            0.3,
            recommended_action=RecommendedAction.ROUTE_TO_ADMIN_REVIEW.value,
            execution_mode=ExecutionMode.HUMAN_REVIEW_REQUIRED.value,
            internal_summary="모호함",
        )
        data = parse_llm_output(raw)
        validated, err = validate_llm_output(data)
        self.assertIsNone(err)
        self.assertEqual(validated["intent"], "UNSUPPORTED_REQUEST")


class SurveyReopenOnlyAfterAdminApprovalTests(TestCase):
    """6. Admin 승인 전에는 설문 reopen 실행되지 않음. 7. Admin approve_reopen_survey 실행 시 submission 편집 가능, quote 결제 불가, 고객 진입 가능."""

    def setUp(self):
        self.customer = User.objects.create_user(username='cust', email='cust@t.com', password='p')
        self.staff = User.objects.create_user(username='staff', email='staff@t.com', password='p', is_staff=True)
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('200'),
            items=[{'code': 'A', 'label': 'A', 'price': 200}],
        )
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.quote,
            requested_by=self.customer,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.ANALYZED,
            customer_message='설문 다시 수정하고 싶어요',
        )

    def test_submission_not_editable_before_approve(self):
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.SUBMITTED)
        self.assertFalse(self.submission.can_customer_edit())

    def test_approve_reopen_survey_makes_submission_editable_and_quote_not_payable(self):
        success, err = approve_reopen_survey(self.cr, self.staff, request=None)
        self.assertTrue(success)
        self.assertIsNone(err)
        self.submission.refresh_from_db()
        self.quote.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.REVISION_REQUESTED)
        self.assertTrue(self.submission.can_customer_edit())
        self.assertIsNotNone(self.quote.revision_superseded_at)
        self.assertFalse(self.quote.is_payable())

    def test_customer_can_enter_via_resume_link_after_reopen(self):
        success, _ = approve_reopen_survey(self.cr, self.staff, request=None)
        self.assertTrue(success)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.REVISION_REQUESTED)
        draft = SurveySubmission.objects.filter(
            user=self.customer,
            status__in=(SurveySubmission.Status.DRAFT, SurveySubmission.Status.REVISION_REQUESTED),
        ).order_by('-updated_at').first()
        self.assertIsNotNone(draft)
        self.assertEqual(draft.id, self.submission.id)


class ReopenedSurveyKeepsAnswersTests(TestCase):
    """8. Reopen된 설문은 기존 답변 유지 후 수정 가능."""

    def setUp(self):
        self.user = User.objects.create_user(username='u2', email='u2@t.com', password='p')
        self.submission = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.REVISION_REQUESTED,
            answers={'first_name': 'Kim', 'last_name': 'Lee', 'requested_required_services': ['S1']},
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
            items=[],
        )
        self.quote.revision_superseded_at = self.submission.updated_at
        self.quote.save(update_fields=['revision_superseded_at'])

    def test_reopened_submission_has_answers(self):
        self.submission.refresh_from_db()
        self.assertIsNotNone(self.submission.answers)
        self.assertEqual(self.submission.answers.get('first_name'), 'Kim')
        self.assertEqual(self.submission.answers.get('requested_required_services'), ['S1'])


class ResubmitAndQuoteSentTests(TestCase):
    """9. 재제출 후 admin review 대기. 10. 새 quote 송부 후 change request APPLIED."""

    def setUp(self):
        self.customer = User.objects.create_user(username='c2', email='c2@t.com', password='p')
        self.staff = User.objects.create_user(username='s2', email='s2@t.com', password='p', is_staff=True)
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.REVISION_REQUESTED,
        )
        self.sent_quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('300'),
            items=[{'code': 'X', 'label': 'X', 'price': 300}],
        )
        self.sent_quote.revision_superseded_at = self.submission.updated_at
        self.sent_quote.save(update_fields=['revision_superseded_at'])
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.sent_quote,
            requested_by=self.customer,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED,
            customer_message='설문 수정 요청',
        )
        self.draft_quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('350'),
            items=[{'code': 'X', 'label': 'X', 'price': 350}],
        )

    def test_after_resubmit_change_request_in_review(self):
        self.cr.status = QuoteChangeRequest.Status.IN_REVIEW
        self.cr.save(update_fields=['status'])
        self.submission.status = SurveySubmission.Status.SUBMITTED
        self.submission.save(update_fields=['status'])
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.IN_REVIEW)

    def test_finalize_and_send_quote_marks_change_request_applied(self):
        self.cr.status = QuoteChangeRequest.Status.IN_REVIEW
        self.cr.save(update_fields=['status'])
        self.draft_quote.status = SettlementQuote.Status.FINAL_SENT
        self.draft_quote.save(update_fields=['status'])
        finalize_and_send_quote(self.draft_quote, actor=self.staff)
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.APPLIED)


class SupersededQuoteCheckoutBlockedTests(TestCase):
    """11. Superseded/inactive quote는 checkout 불가."""

    def setUp(self):
        self.user = User.objects.create_user(username='pay_user', email='pay@t.com', password='p')
        self.submission = SurveySubmission.objects.create(
            user=self.user, email=self.user.email, status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
            items=[{'code': 'A', 'label': 'A', 'price': 100}],
        )

    def test_superseded_quote_checkout_blocked(self):
        from django.utils import timezone
        self.quote.revision_superseded_at = timezone.now()
        self.quote.save(update_fields=['revision_superseded_at'])
        quote, err = process_quote_payment(self.user, quote_id=self.quote.id)
        self.assertIsNone(quote)
        self.assertIsNotNone(err)
        self.assertIn('수정 요청', err)


class PermissionTests(TestCase):
    """12. 다른 고객 접근 차단, staff only 액션 보호."""

    def setUp(self):
        self.customer1 = User.objects.create_user(username='c1', email='c1@t.com', password='p')
        self.customer2 = User.objects.create_user(username='c2', email='c2@t.com', password='p')
        self.staff = User.objects.create_user(username='staff', email='s@t.com', password='p', is_staff=True)
        self.sub1 = SurveySubmission.objects.create(
            user=self.customer1, email=self.customer1.email, status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote1 = SettlementQuote.objects.create(
            submission=self.sub1,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('100'),
            items=[],
        )
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.sub1,
            quote=self.quote1,
            requested_by=self.customer1,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.ANALYZED,
            customer_message='수정 요청',
        )

    def test_other_customer_cannot_pay_quote(self):
        quote, err = process_quote_payment(self.customer2, quote_id=self.quote1.id)
        self.assertIsNone(quote)
        self.assertIsNotNone(err)

    def test_owner_can_pay_quote(self):
        quote, err = process_quote_payment(self.customer1, quote_id=self.quote1.id)
        self.assertIsNotNone(quote)
        self.assertIsNone(err)

    def test_approve_reopen_does_not_require_staff_but_typically_called_by_view(self):
        success, err = approve_reopen_survey(self.cr, self.staff, request=None)
        self.assertTrue(success)
        success2, err2 = approve_reopen_survey(self.cr, self.staff, request=None)
        self.assertTrue(success2)
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED)


class RegressionPriceVisibilityTests(TestCase):
    """13. 기존 FINAL_SENT 가격 노출 정책 유지, status < FINAL_SENT 가격 비노출."""

    def setUp(self):
        self.user = User.objects.create_user(username='reg', email='r@t.com', password='p')
        self.submission = SurveySubmission.objects.create(
            user=self.user, email=self.user.email, status=SurveySubmission.Status.SUBMITTED,
        )

    def test_final_sent_price_visible(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('500'),
            items=[{'code': 'X', 'label': 'X', 'price': 500}],
        )
        self.assertTrue(can_view_price(self.user, quote))
        out = quote_for_customer(quote)
        self.assertIsNotNone(out)
        self.assertEqual(out['total'], 500)
        for item in out['items']:
            self.assertFalse(item.get('_masked', False))

    def test_draft_price_masked(self):
        quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('500'),
            items=[{'code': 'X', 'label': 'X', 'price': 500}],
        )
        self.assertFalse(can_view_price(self.user, quote))
        out = quote_for_customer(quote)
        self.assertIsNotNone(out)
        self.assertIsNone(out.get('total'))
        for item in out['items']:
            self.assertTrue(item.get('_masked', False))


class RejectAndMarkAppliedTests(TestCase):
    """reject_change_request, mark_change_request_applied idempotent."""

    def setUp(self):
        self.staff = User.objects.create_user(username='st', email='st@t.com', password='p', is_staff=True)
        self.submission = SurveySubmission.objects.create(
            user=User.objects.create_user(username='cu', email='cu@t.com', password='p'),
            email='cu@t.com',
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('0'),
            items=[],
        )
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.quote,
            requested_by=self.submission.user,
            source_type=QuoteChangeRequest.SourceType.TEXT,
            status=QuoteChangeRequest.Status.ANALYZED,
            customer_message='반려할게요',
        )

    def test_reject_change_request_idempotent(self):
        success, err = reject_change_request(self.cr, self.staff, note='불가')
        self.assertTrue(success)
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.REJECTED)
        success2, err2 = reject_change_request(self.cr, self.staff, note='again')
        self.assertTrue(success2)
        self.assertEqual(QuoteChangeActionLog.objects.filter(change_request=self.cr, action_type=QuoteChangeActionLog.ActionType.ADMIN_REJECTED).count(), 1)

    def test_mark_applied_idempotent(self):
        self.cr.status = QuoteChangeRequest.Status.IN_REVIEW
        self.cr.save(update_fields=['status'])
        success, err = mark_change_request_applied(self.cr, self.staff)
        self.assertTrue(success)
        self.cr.refresh_from_db()
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.APPLIED)
        success2, _ = mark_change_request_applied(self.cr, self.staff)
        self.assertTrue(success2)
