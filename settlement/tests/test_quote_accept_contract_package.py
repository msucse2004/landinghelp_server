from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from messaging.models import Conversation, Message
from settlement.notifications import send_contract_package_to_customer
from settlement.quote_acceptance import accept_quote, create_contract_package_for_submission
from settlement.models import CaseDocument, SettlementQuote
from survey.models import SurveySubmission


User = get_user_model()


class QuoteAcceptContractPackageTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='accept_customer',
            email='accept_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.hq_staff = User.objects.create_user(
            username='accept_hq_staff',
            email='accept_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.agent = User.objects.create_user(
            username='accept_agent',
            email='accept_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
            case_stage=SurveySubmission.CaseStage.QUOTE_SENT,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('1200'),
            items=[{'code': 'SVC1', 'label': 'Service 1', 'price': 1200}],
        )

    def test_accept_quote_updates_stage_and_keeps_quote_not_paid(self):
        result = accept_quote(self.customer, quote_id=self.quote.id)

        self.submission.refresh_from_db()
        self.quote.refresh_from_db()

        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.QUOTE_ACCEPTED)
        self.assertEqual(self.quote.status, SettlementQuote.Status.FINAL_SENT)
        self.assertEqual(len(result['documents']), 3)

        doc_types = set(
            CaseDocument.objects.filter(submission=self.submission).values_list('document_type', flat=True)
        )
        self.assertEqual(
            doc_types,
            {
                CaseDocument.DocumentType.INVOICE,
                CaseDocument.DocumentType.CONSENT_FORM,
                CaseDocument.DocumentType.POWER_OF_ATTORNEY,
            },
        )

        for doc in CaseDocument.objects.filter(submission=self.submission):
            self.assertEqual(doc.status, CaseDocument.Status.GENERATED)
            expected_customer_action = doc.document_type in {
                CaseDocument.DocumentType.CONSENT_FORM,
                CaseDocument.DocumentType.POWER_OF_ATTORNEY,
            }
            self.assertEqual(bool((doc.metadata or {}).get('customer_action_required')), expected_customer_action)
            self.assertEqual((doc.metadata or {}).get('signature_status'), 'READY_FOR_SIGNATURE')

        hq_conv = Conversation.objects.filter(
            survey_submission=self.submission,
            workspace_type=Conversation.WorkspaceType.HQ_BACKOFFICE,
        ).first()
        self.assertIsNotNone(hq_conv)
        self.assertTrue(Message.objects.filter(conversation=hq_conv, body__icontains='계약 패키지').exists())

    def test_send_contract_package_authority_is_internal_only(self):
        docs = create_contract_package_for_submission(self.submission, quote=self.quote, generated_by=self.customer)

        denied_for_customer = send_contract_package_to_customer(self.submission, docs, sender=self.customer)
        denied_for_agent = send_contract_package_to_customer(self.submission, docs, sender=self.agent)
        allowed_for_hq = send_contract_package_to_customer(self.submission, docs, sender=self.hq_staff)

        self.assertFalse(denied_for_customer)
        self.assertFalse(denied_for_agent)
        self.assertTrue(allowed_for_hq)

    def test_api_quote_accept_and_my_quote_package_list(self):
        self.client.force_login(self.customer)

        accept_url = reverse('api_settlement_quote_accept')
        accept_response = self.client.post(accept_url, {'quote_id': self.quote.id})
        self.assertEqual(accept_response.status_code, 302)

        my_quote_url = reverse('api_settlement_my_quote')
        payload = self.client.get(my_quote_url).json()
        self.assertTrue(payload.get('ok'))
        package_docs = payload.get('contract_package_documents') or []
        self.assertGreaterEqual(len(package_docs), 3)
