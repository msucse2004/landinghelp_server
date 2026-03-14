"""
설문·견적서·변경요청 상태기(survey/quote/change request) 검증 테스트.

- SurveySubmission: DRAFT → SUBMITTED → [REVISION_REQUESTED ↔ SUBMITTED] → AWAITING_PAYMENT → AGENT_ASSIGNMENT → SERVICE_IN_PROGRESS
- SettlementQuote: DRAFT → FINAL_SENT → PAID, 설문 재개 시 기존 FINAL_SENT에 revision_superseded_at
- QuoteChangeRequest: OPEN → ANALYZED → (승인 시) CUSTOMER_ACTION_REQUIRED → (재제출 시) IN_REVIEW → (송부 시) APPLIED
- 고객 메시지로 자동 REVISION_REQUESTED 전환은 SUBMITTED/AWAITING_PAYMENT에서만 허용

Run: python manage.py test settlement.tests.test_survey_quote_state_machine
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model

from survey.models import SurveySubmission, SurveySubmissionEvent
from settlement.models import (
    SettlementQuote,
    QuoteChangeRequest,
    QuoteChangeActionLog,
)
from settlement.quote_approval import finalize_and_send_quote
from settlement.quote_checkout import process_quote_payment
from settlement.services_quote_change import approve_reopen_survey

User = get_user_model()


class SurveySubmissionStateMachineTests(TestCase):
    """SurveySubmission 유효 전이 및 can_customer_edit 일관성."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='cust_sm',
            email='cust_sm@test.com',
            password='testpass123',
        )

    def test_draft_can_customer_edit(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.DRAFT,
        )
        self.assertTrue(sub.can_customer_edit())

    def test_submitted_cannot_customer_edit(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.assertFalse(sub.can_customer_edit())

    def test_revision_requested_can_customer_edit(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.REVISION_REQUESTED,
        )
        self.assertTrue(sub.can_customer_edit())

    def test_awaiting_payment_cannot_customer_edit(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
        )
        self.assertFalse(sub.can_customer_edit())

    def test_valid_transition_submitted_to_revision_requested(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        sub.status = SurveySubmission.Status.REVISION_REQUESTED
        sub.save(update_fields=['status'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, SurveySubmission.Status.REVISION_REQUESTED)
        self.assertTrue(sub.can_customer_edit())

    def test_valid_transition_revision_requested_to_submitted(self):
        sub = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.REVISION_REQUESTED,
        )
        sub.status = SurveySubmission.Status.SUBMITTED
        sub.save(update_fields=['status'])
        sub.refresh_from_db()
        self.assertEqual(sub.status, SurveySubmission.Status.SUBMITTED)
        self.assertFalse(sub.can_customer_edit())


class SettlementQuoteAndSubmissionFlowTests(TestCase):
    """견적 송부 시 submission → AWAITING_PAYMENT, 결제 시 → AGENT_ASSIGNMENT."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='pay_flow',
            email='pay_flow@test.com',
            password='testpass123',
        )
        self.submission = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.DRAFT,
            total=Decimal('300'),
            items=[{'code': 'S1', 'label': 'Service', 'price': 300}],
        )

    @patch('settlement.notifications.send_quote_release_message')
    @patch('settlement.quote_email.send_quote_release_email_with_attachments', return_value=True)
    def test_finalize_and_send_quote_sets_submission_awaiting_payment(self, mock_email, mock_msg):
        ok, err = finalize_and_send_quote(self.quote, actor=None)
        self.assertTrue(ok, msg=err)
        self.submission.refresh_from_db()
        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, SettlementQuote.Status.FINAL_SENT)
        self.assertEqual(self.submission.status, SurveySubmission.Status.AWAITING_PAYMENT)

    @patch('settlement.scheduling_engine.ensure_submission_schedule_draft', return_value=(None, False))
    @patch('settlement.post_payment.ensure_plan_service_tasks')
    @patch('settlement.post_payment.build_initial_schedule_from_quote', return_value={'2026-01-01': []})
    def test_process_quote_payment_sets_submission_agent_assignment(self, mock_build, mock_ensure, mock_auto_draft):
        self.quote.status = SettlementQuote.Status.FINAL_SENT
        self.quote.save(update_fields=['status'])
        self.submission.status = SurveySubmission.Status.AWAITING_PAYMENT
        self.submission.save(update_fields=['status'])
        quote, err = process_quote_payment(self.user, quote_id=self.quote.id)
        self.assertIsNone(err)
        self.assertIsNotNone(quote)
        self.submission.refresh_from_db()
        self.assertEqual(quote.status, SettlementQuote.Status.PAID)
        self.assertEqual(self.submission.status, SurveySubmission.Status.AGENT_ASSIGNMENT)
        mock_auto_draft.assert_called_once_with(self.submission, actor=self.user)


class QuoteChangeRequestReopenEligibilityTests(TestCase):
    """can_be_reopened_for_survey_edit: submission SUBMITTED/AWAITING_PAYMENT + cr ANALYZED/IN_REVIEW/APPROVED."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='cr_flow',
            email='cr_flow@test.com',
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
            total=Decimal('100'),
            items=[{'code': 'X', 'label': 'X', 'price': 100}],
        )
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.quote,
            requested_by=self.user,
            status=QuoteChangeRequest.Status.ANALYZED,
            customer_message='설문 수정하고 싶어요',
        )

    def test_can_be_reopened_when_submitted_and_analyzed(self):
        self.assertTrue(self.cr.can_be_reopened_for_survey_edit())

    def test_can_be_reopened_when_awaiting_payment_and_in_review(self):
        self.submission.status = SurveySubmission.Status.AWAITING_PAYMENT
        self.submission.save(update_fields=['status'])
        self.cr.status = QuoteChangeRequest.Status.IN_REVIEW
        self.cr.save(update_fields=['status'])
        self.assertTrue(self.cr.can_be_reopened_for_survey_edit())

    def test_cannot_be_reopened_when_agent_assignment(self):
        self.submission.status = SurveySubmission.Status.AGENT_ASSIGNMENT
        self.submission.save(update_fields=['status'])
        self.assertFalse(self.cr.can_be_reopened_for_survey_edit())

    def test_cannot_be_reopened_when_service_in_progress(self):
        self.submission.status = SurveySubmission.Status.SERVICE_IN_PROGRESS
        self.submission.save(update_fields=['status'])
        self.assertFalse(self.cr.can_be_reopened_for_survey_edit())

    @patch('settlement.notifications.send_survey_reopened_customer_message')
    def test_approve_reopen_survey_sets_revision_requested(self, mock_send):
        admin = User.objects.create_user(
            username='admin_sm',
            email='admin_sm@test.com',
            password='adminpass',
            is_staff=True,
        )
        success, err = approve_reopen_survey(self.cr, admin)
        self.assertTrue(success, msg=err)
        self.submission.refresh_from_db()
        self.cr.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.REVISION_REQUESTED)
        self.assertEqual(self.cr.status, QuoteChangeRequest.Status.CUSTOMER_ACTION_REQUIRED)


def _policy_for_survey_reopen(text, context=None, **kw):
    """
    테스트용: 설문 수정 의도 메시지 + 허용 상태면 OFFER_SURVEY_REOPEN,
    AGENT_ASSIGNMENT/SERVICE_IN_PROGRESS면 오퍼 생성 안 함(휴리스틱 위임).
    """
    from customer_request_policy import (
        _heuristic_policy,
        Intent,
        RecommendedAction,
        ExecutionMode,
        HumanReviewTarget,
        PolicyResult,
    )
    ctx = context or {}
    st = ctx.get("submission_status")
    if st in (SurveySubmission.Status.AGENT_ASSIGNMENT, SurveySubmission.Status.SERVICE_IN_PROGRESS):
        return _heuristic_policy(text)
    s = (text or "").strip().lower()
    if "설문" in s and any(x in s for x in ("수정", "편집", "다시", "edit", "revise", "reopen")):
        return PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.8,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="test policy",
            should_create_action_offer=True,
        )
    if "survey" in s and any(x in s for x in ("edit", "revise", "reopen", "change")):
        return PolicyResult(
            detected_intent=Intent.SURVEY_REOPEN_REQUEST,
            recommended_action=RecommendedAction.OFFER_SURVEY_REOPEN,
            execution_mode=ExecutionMode.AUTO_CONFIRMABLE,
            confidence=0.8,
            human_review_target=HumanReviewTarget.none,
            customer_facing_summary="설문을 다시 수정할 수 있도록 열어드릴까요?",
            internal_reasoning_summary="test policy",
            should_create_action_offer=True,
        )
    return _heuristic_policy(text)


class CustomerMessageAutoReopenTests(TestCase):
    """
    고객 메시지 → 통합 서비스(handle_customer_request_flow) 흐름.
    상태 전이는 고객이 action offer 버튼을 누를 때만 발생. 메시지 수신 시에는 offer 생성·자동 응답만.
    """

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant, Message
        self.customer = User.objects.create_user(
            username='cust_msg',
            email='cust_msg@test.com',
            password='testpass123',
        )
        self.staff = User.objects.create_user(
            username='staff_msg',
            email='staff_msg@test.com',
            password='staffpass',
            is_staff=True,
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.conv = Conversation.objects.create(
            type=Conversation.Type.NOTICE,
            survey_submission=self.submission,
            subject='정착 서비스',
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)
        self._Message = Message

    def _send_customer_message_and_handle(self, body: str):
        msg = self._Message.objects.create(
            conversation=self.conv,
            sender=self.customer,
            body=body,
        )
        from customer_request_service import handle_customer_request_flow
        # 테스트에서 정책을 고정해 LLM/휴리스틱 순서에 의존하지 않음
        with patch("customer_request_policy.evaluate_customer_request_policy", side_effect=lambda text, context=None, **kw: _policy_for_survey_reopen(text, context)):
            handle_customer_request_flow(
                'messaging_inbox',
                self.customer,
                body,
                conversation=self.conv,
                message=msg,
            )
        return msg

    def test_submitted_survey_edit_message_creates_offer_not_immediate_status_change(self):
        self._send_customer_message_and_handle('설문을 수정하고 싶습니다.')
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status,
            SurveySubmission.Status.SUBMITTED,
            '메시지 수신만으로는 상태 변경 없음; action offer 생성 후 고객 버튼 클릭 시에만 REVISION_REQUESTED',
        )
        from settlement.models import CustomerActionOffer
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key='reopen_survey',
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNotNone(offer, '설문 수정 메시지 시 reopen_survey offer 생성되어야 함')

    def test_awaiting_payment_survey_edit_message_creates_offer(self):
        self.submission.status = SurveySubmission.Status.AWAITING_PAYMENT
        self.submission.save(update_fields=['status'])
        self._send_customer_message_and_handle('I want to edit my survey.')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.AWAITING_PAYMENT)
        from settlement.models import CustomerActionOffer
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key='reopen_survey',
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNotNone(offer)

    def test_no_offer_from_agent_assignment(self):
        self.submission.status = SurveySubmission.Status.AGENT_ASSIGNMENT
        self.submission.save(update_fields=['status'])
        self._send_customer_message_and_handle('설문 수정하고 싶어요.')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.AGENT_ASSIGNMENT)
        from settlement.models import CustomerActionOffer
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key='reopen_survey',
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNone(offer, 'AGENT_ASSIGNMENT에서는 reopen offer 생성되지 않음')

    def test_no_offer_from_service_in_progress(self):
        self.submission.status = SurveySubmission.Status.SERVICE_IN_PROGRESS
        self.submission.save(update_fields=['status'])
        self._send_customer_message_and_handle('설문을 다시 수정하고 싶습니다.')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.SERVICE_IN_PROGRESS)
        from settlement.models import CustomerActionOffer
        offer = CustomerActionOffer.objects.filter(
            submission=self.submission,
            button_action_key='reopen_survey',
            status=CustomerActionOffer.Status.PENDING,
        ).first()
        self.assertIsNone(offer)

    def test_already_revision_requested_no_duplicate_offer_or_status_change(self):
        self.submission.status = SurveySubmission.Status.REVISION_REQUESTED
        self.submission.save(update_fields=['status'])
        self._send_customer_message_and_handle('설문 수정할게요.')
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, SurveySubmission.Status.REVISION_REQUESTED)

    def test_quote_resend_message_does_not_change_submission_status(self):
        self._send_customer_message_and_handle('견적서만 다시 보내주세요.')
        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status,
            SurveySubmission.Status.SUBMITTED,
            '설문 수정 의도가 없으면 상태 유지',
        )


class SettlementQuoteSupersededTests(TestCase):
    """설문 재개 승인 시 기존 FINAL_SENT 견적에 revision_superseded_at 설정."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='sup_cust',
            email='sup_cust@test.com',
            password='testpass123',
        )
        self.admin = User.objects.create_user(
            username='sup_admin',
            email='sup_admin@test.com',
            password='adminpass',
            is_staff=True,
        )
        self.submission = SurveySubmission.objects.create(
            user=self.user,
            email=self.user.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.sent_quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('500'),
            items=[{'code': 'S1', 'label': 'S1', 'price': 500}],
        )
        self.cr = QuoteChangeRequest.objects.create(
            submission=self.submission,
            quote=self.sent_quote,
            requested_by=self.user,
            status=QuoteChangeRequest.Status.ANALYZED,
            customer_message='설문 수정 요청',
        )

    @patch('settlement.notifications.send_survey_reopened_customer_message')
    def test_approve_reopen_sets_sent_quote_superseded(self, mock_send):
        self.assertIsNone(self.sent_quote.revision_superseded_at)
        success, err = approve_reopen_survey(self.cr, self.admin)
        self.assertTrue(success, msg=err)
        self.sent_quote.refresh_from_db()
        self.assertIsNotNone(
            self.sent_quote.revision_superseded_at,
            '설문 재개 승인 시 기존 송부 견적에 revision_superseded_at 설정',
        )
        self.assertFalse(self.sent_quote.is_payable())
