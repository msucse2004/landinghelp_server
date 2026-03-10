"""
메시지함 경로에서 고객 메시지 전송 시 handle_customer_request_flow 사용 검증.
[COMMON SERVICE LOGIC] 메시지함과 customer quote 경로가 같은 통합 서비스 사용.
Run: python manage.py test messaging.tests.test_customer_message_request_flow -v 2
"""
import json
import sys
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from survey.models import SurveySubmission
from messaging.models import Conversation, ConversationParticipant, Message

User = get_user_model()


def _progress(msg: str) -> None:
    print(msg, flush=True)
    sys.stdout.flush()


class MessagingPathUsesIntegratedServiceTests(TestCase):
    """메시지 POST 시 customer_request_service.handle_customer_request_flow 호출 확인."""

    def setUp(self):
        self.customer = User.objects.create_user(
            username="msg_flow_cust",
            email="msg_flow@test.com",
            password="testpass123",
        )
        self.staff = User.objects.create_user(
            username="msg_flow_staff",
            email="msg_flow_s@test.com",
            password="staff123",
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
        ConversationParticipant.objects.create(conversation=self.conv, user=self.staff)

    @patch("customer_request_service.handle_customer_request_flow")
    def test_messaging_post_invokes_handle_customer_request_flow(self, mock_flow):
        _progress("[COMMON SERVICE] messaging path uses handle_customer_request_flow")
        from customer_request_service import handle_customer_request_flow as real_flow
        mock_flow.side_effect = real_flow
        url = reverse("messaging:conversation_messages", kwargs={"conversation_id": self.conv.id})
        self.client.force_login(self.customer)
        resp = self.client.post(
            url,
            data=json.dumps({"body": "설문 다시 수정하고 싶어요"}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertGreaterEqual(mock_flow.call_count, 1, "handle_customer_request_flow 호출됨")
        call_args, call_kw = mock_flow.call_args
        self.assertEqual(call_args[0], "messaging_inbox")
        self.assertEqual(call_kw.get("conversation").id, self.conv.id)
        self.assertIsNotNone(call_kw.get("message"))
