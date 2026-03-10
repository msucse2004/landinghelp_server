"""
[ADMIN INITIATED REOPEN] Admin이 설문 수정 허용 → 즉시 REVISION_REQUESTED 전환 → 고객은 설문 수정하기만 클릭.
Run: python manage.py test settlement.tests.test_admin_initiated_reopen -v 2
"""
import sys

from django.test import TestCase
from django.contrib.auth import get_user_model

from survey.models import SurveySubmission
from customer_request_service import (
    admin_initiated_reopen_submission,
    get_submission_reopen_status,
    build_customer_ui_payload,
)

User = get_user_model()


def _progress(msg: str) -> None:
    print(msg, flush=True)
    sys.stdout.flush()


class AdminInitiatedReopenTests(TestCase):
    """Admin이 reopen 실행 → 즉시 REVISION_REQUESTED → 고객은 설문 수정하기 링크로 바로 수정."""

    def setUp(self):
        from messaging.models import Conversation, ConversationParticipant
        self.customer = User.objects.create_user(
            username="admin_reopen_cust",
            email="admin_reopen@test.com",
            password="testpass123",
        )
        self.admin = User.objects.create_user(
            username="admin_reopen_admin",
            email="admin_reopen_a@test.com",
            password="admin123",
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
            subject="정착",
        )
        ConversationParticipant.objects.create(conversation=self.conv, user=self.customer)
        ConversationParticipant.objects.create(conversation=self.conv, user=self.admin)

    def test_admin_reopen_immediately_sets_revision_requested(self):
        _progress("[8/10] verify admin initiated reopen - immediate REVISION_REQUESTED")
        success, offer, err = admin_initiated_reopen_submission(
            self.submission.id, self.admin
        )
        self.assertTrue(success, msg=err)
        self.assertIsNone(offer, "간소화: offer를 생성하지 않고 직접 상태 전환")

        self.submission.refresh_from_db()
        self.assertEqual(
            self.submission.status,
            SurveySubmission.Status.REVISION_REQUESTED,
            "Admin 실행 직후 바로 REVISION_REQUESTED",
        )

        status = get_submission_reopen_status(self.submission)
        self.assertEqual(
            status.get("submission_status"),
            SurveySubmission.Status.REVISION_REQUESTED,
            "reopen 상태 정보에 REVISION_REQUESTED 반영",
        )

        payload = build_customer_ui_payload(self.customer, submission=self.submission)
        self.assertTrue(
            payload.get("can_reopen_survey"),
            "고객 UI payload에 설문 수정 가능 표시",
        )

    def test_admin_reopen_idempotent_when_already_revision_requested(self):
        _progress("[8b/10] verify admin reopen idempotent")
        self.submission.status = SurveySubmission.Status.REVISION_REQUESTED
        self.submission.save(update_fields=["status"])

        success, offer, err = admin_initiated_reopen_submission(
            self.submission.id, self.admin
        )
        self.assertTrue(success)
        self.assertIsNone(offer)
        self.assertIsNone(err)
