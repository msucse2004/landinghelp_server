from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from messaging.models import ConversationParticipant
from messaging.workspace import get_or_create_hq_workspace, get_or_create_local_workspace
from survey.models import SurveySubmission


User = get_user_model()


class WorkspaceAccessControlTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='ws_customer',
            email='ws_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='ws_agent',
            email='ws_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )
        self.staff = User.objects.create_user(
            username='ws_staff',
            email='ws_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )

        self.hq_conv = get_or_create_hq_workspace(self.submission)
        self.local_conv = get_or_create_local_workspace(self.submission, agent=self.agent)

    def test_agent_denied_from_hq_workspace_even_if_added_as_participant(self):
        ConversationParticipant.objects.get_or_create(conversation=self.hq_conv, user=self.agent)

        self.client.force_login(self.agent)
        url = reverse('messaging:conversation_detail', kwargs={'conversation_id': self.hq_conv.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)

    def test_agent_sees_only_local_workspace_in_conversation_list(self):
        ConversationParticipant.objects.get_or_create(conversation=self.hq_conv, user=self.agent)

        self.client.force_login(self.agent)
        url = reverse('messaging:conversation_list')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        conversation_ids = {item['id'] for item in payload.get('conversations', [])}
        self.assertIn(self.local_conv.id, conversation_ids)
        self.assertNotIn(self.hq_conv.id, conversation_ids)
