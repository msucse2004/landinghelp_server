from django.contrib.auth import get_user_model
from django.test import TestCase

from messaging.models import Conversation, Message
from settlement.models import SettlementQuote
from settlement.notifications import send_quote_sent_customer_message, send_schedule_sent_to_customer
from survey.models import SurveySubmission


User = get_user_model()


class WorkspaceRoutingNotificationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='ws_route_staff',
            email='ws_route_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='ws_route_customer',
            email='ws_route_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            items=[{'code': 'svc_1', 'label': 'Service 1', 'price': 1000}],
            total=1000,
        )

    def test_quote_message_routes_to_hq_workspace(self):
        sent = send_quote_sent_customer_message(self.quote, language_code='ko')
        self.assertTrue(sent)

        hq_conv = Conversation.objects.get(
            survey_submission=self.submission,
            workspace_type=Conversation.WorkspaceType.HQ_BACKOFFICE,
        )
        self.assertTrue(Message.objects.filter(conversation=hq_conv, body__icontains='견적서를 보냈습니다').exists())

    def test_schedule_message_routes_to_local_workspace(self):
        sent = send_schedule_sent_to_customer(self.submission, language_code='ko')
        self.assertTrue(sent)

        local_conv = Conversation.objects.get(
            survey_submission=self.submission,
            workspace_type=Conversation.WorkspaceType.LOCAL_EXECUTION,
        )
        self.assertTrue(Message.objects.filter(conversation=local_conv, body__icontains='일정이').exists())
