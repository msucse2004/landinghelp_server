from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from messaging.models import Conversation, Message
from settlement.document_signatures import sign_case_document
from settlement.models import CaseDocument, DocumentSignature, SettlementQuote
from settlement.quote_acceptance import create_contract_package_for_submission
from survey.models import SurveySubmission


User = get_user_model()


class DocumentSignatureWorkflowTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='sign_customer',
            email='sign_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.hq_staff = User.objects.create_user(
            username='sign_hq_staff',
            email='sign_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.AWAITING_PAYMENT,
            case_stage=SurveySubmission.CaseStage.QUOTE_ACCEPTED,
        )
        self.quote = SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            total=Decimal('1500'),
            items=[{'code': 'SVC1', 'label': 'Service 1', 'price': 1500}],
        )
        create_contract_package_for_submission(
            submission=self.submission,
            quote=self.quote,
            generated_by=self.hq_staff,
        )

    def _doc(self, document_type):
        return CaseDocument.objects.filter(
            submission=self.submission,
            document_type=document_type,
            metadata__package_source='QUOTE_ACCEPTANCE',
        ).order_by('-created_at').first()

    def test_customer_signs_consent_and_poa_only(self):
        invoice = self._doc(CaseDocument.DocumentType.INVOICE)
        consent = self._doc(CaseDocument.DocumentType.CONSENT_FORM)
        poa = self._doc(CaseDocument.DocumentType.POWER_OF_ATTORNEY)

        with self.assertRaises(PermissionDenied):
            sign_case_document(document=invoice, signer=self.customer)

        result_consent = sign_case_document(document=consent, signer=self.customer)
        result_poa = sign_case_document(document=poa, signer=self.customer)

        self.assertFalse(result_consent['required_complete'])
        self.assertFalse(result_poa['required_complete'])
        self.assertIsNone(result_poa['final_package_document'])

        self.assertTrue(DocumentSignature.objects.filter(document=consent, signer_role=DocumentSignature.SignerRole.CUSTOMER).exists())
        self.assertTrue(DocumentSignature.objects.filter(document=poa, signer_role=DocumentSignature.SignerRole.CUSTOMER).exists())

    def test_all_required_signatures_create_signed_final_archive(self):
        consent = self._doc(CaseDocument.DocumentType.CONSENT_FORM)
        poa = self._doc(CaseDocument.DocumentType.POWER_OF_ATTORNEY)
        invoice = self._doc(CaseDocument.DocumentType.INVOICE)

        sign_case_document(document=consent, signer=self.customer)
        sign_case_document(document=poa, signer=self.customer)
        result_internal = sign_case_document(document=invoice, signer=self.hq_staff)

        final_package = result_internal['final_package_document']
        self.assertIsNotNone(final_package)
        self.assertEqual(final_package.document_type, CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE)
        self.assertTrue(final_package.is_signed_final)
        self.assertTrue((final_package.metadata or {}).get('archived_server_side'))

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.case_stage, SurveySubmission.CaseStage.CONTRACT_FULLY_SIGNED)

        originals = CaseDocument.objects.filter(
            submission=self.submission,
            document_type__in=[
                CaseDocument.DocumentType.INVOICE,
                CaseDocument.DocumentType.CONSENT_FORM,
                CaseDocument.DocumentType.POWER_OF_ATTORNEY,
            ],
            metadata__package_source='QUOTE_ACCEPTANCE',
        )
        self.assertEqual(originals.count(), 3)
        for doc in originals:
            self.assertEqual(doc.status, CaseDocument.Status.ARCHIVED)
            self.assertEqual((doc.metadata or {}).get('signature_status'), 'SIGNED')
            self.assertEqual((doc.metadata or {}).get('signed_final_package_id'), final_package.id)

        hq_conv = Conversation.objects.filter(
            survey_submission=self.submission,
            workspace_type=Conversation.WorkspaceType.HQ_BACKOFFICE,
        ).first()
        self.assertIsNotNone(hq_conv)
        self.assertTrue(Message.objects.filter(conversation=hq_conv, body__icontains='최종').exists())

    def test_signing_is_idempotent_per_document_role(self):
        consent = self._doc(CaseDocument.DocumentType.CONSENT_FORM)

        first = sign_case_document(document=consent, signer=self.customer)
        second = sign_case_document(document=consent, signer=self.customer)

        self.assertFalse(first['already_signed'])
        self.assertTrue(second['already_signed'])
        self.assertEqual(
            DocumentSignature.objects.filter(document=consent, signer_role=DocumentSignature.SignerRole.CUSTOMER).count(),
            1,
        )

    def test_api_sign_case_document_and_my_quote_payload(self):
        consent = self._doc(CaseDocument.DocumentType.CONSENT_FORM)
        poa = self._doc(CaseDocument.DocumentType.POWER_OF_ATTORNEY)
        invoice = self._doc(CaseDocument.DocumentType.INVOICE)

        self.client.force_login(self.customer)
        sign_url = reverse('api_settlement_case_document_sign', kwargs={'document_id': consent.id})
        response = self.client.post(sign_url, {'signer_role': 'CUSTOMER'})
        self.assertEqual(response.status_code, 302)

        sign_url = reverse('api_settlement_case_document_sign', kwargs={'document_id': poa.id})
        response = self.client.post(sign_url, {'signer_role': 'CUSTOMER'})
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.hq_staff)
        sign_url = reverse('api_settlement_case_document_sign', kwargs={'document_id': invoice.id})
        response = self.client.post(sign_url, {'signer_role': 'INTERNAL'})
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.customer)
        payload = self.client.get(reverse('api_settlement_my_quote')).json()
        self.assertTrue(payload.get('ok'))
        final_package = payload.get('signed_final_package_document')
        self.assertIsNotNone(final_package)
        self.assertEqual(final_package.get('document_type'), CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE)
