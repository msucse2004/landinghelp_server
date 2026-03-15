from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from settlement.models import (
    CaseDocument,
    ServiceCompletionForm,
    ServiceSchedulePlan,
    SettlementQuote,
)
from survey.models import SurveySubmission


User = get_user_model()


class CaseHistoryReportApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='history_admin',
            email='history_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.supervisor = User.objects.create_user(
            username='history_supervisor',
            email='history_supervisor@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
            is_staff=True,
        )
        self.hq_staff = User.objects.create_user(
            username='history_hq_staff',
            email='history_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='history_customer',
            email='history_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='history_other_customer',
            email='history_other_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='history_agent',
            email='history_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SERVICE_IN_PROGRESS,
            case_stage=SurveySubmission.CaseStage.SERVICES_IN_PROGRESS,
        )
        self.other_submission = SurveySubmission.objects.create(
            user=self.other_customer,
            email=self.other_customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )

        self.plan = ServiceSchedulePlan.objects.create(
            submission=self.submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )

        SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.FINAL_SENT,
            version=1,
            total=Decimal('1500'),
            items=[{'code': 'S1', 'label': 'Service 1', 'price': 1500}],
        )
        SettlementQuote.objects.create(
            submission=self.submission,
            status=SettlementQuote.Status.PAID,
            version=2,
            total=Decimal('1800'),
            items=[{'code': 'S1', 'label': 'Service 1', 'price': 1800}],
        )

        self._create_doc(CaseDocument.DocumentType.INVOICE, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.INVOICE, 2, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.CONSENT_FORM, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.POWER_OF_ATTORNEY, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.UTILITY_CONFIRMATION, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.CUSTOMER_REQUESTED_DOCUMENT, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.SERVICE_COMPLETION_FORM, 1, CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER)
        self._create_doc(CaseDocument.DocumentType.REAL_ESTATE_CONTRACT, 1, CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER)

        ServiceCompletionForm.objects.create(
            submission=self.submission,
            agent=self.agent,
            schedule_plan=self.plan,
            status=ServiceCompletionForm.Status.REVIEWED,
            summary='서비스 완료',
            completion_notes='완료 노트',
            attachments_count=1,
            submitted_at=timezone.now(),
            reviewed_at=timezone.now(),
            reviewed_by=self.admin,
        )

    def _create_doc(self, doc_type, version, visibility_level):
        return CaseDocument.objects.create(
            submission=self.submission,
            document_type=doc_type,
            document_scope=CaseDocument.DocumentScope.CASE,
            visibility_level=visibility_level,
            uploaded_by=self.admin,
            owner_user=self.customer,
            file=SimpleUploadedFile(f'{doc_type.lower()}_{version}.txt', b'dummy', content_type='text/plain'),
            original_filename=f'{doc_type.lower()}_{version}.txt',
            status=CaseDocument.Status.GENERATED,
            version=version,
            metadata={},
        )

    def _doc_group_by_type(self, payload, document_type):
        groups = payload['report']['document_groups']
        for group in groups:
            if group['document_type'] == document_type:
                return group
        return None

    def test_customer_history_api_returns_shared_only_and_version_grouping(self):
        self.client.force_login(self.customer)
        url = reverse('api_settlement_case_history_my')
        response = self.client.get(url, {'submission_id': self.submission.id})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['report']['access_scope'], 'CUSTOMER_SHARED_ONLY')

        invoice_group = self._doc_group_by_type(payload, CaseDocument.DocumentType.INVOICE)
        self.assertIsNotNone(invoice_group)
        self.assertEqual([item['version'] for item in invoice_group['items']], [2, 1])

        real_estate_group = self._doc_group_by_type(payload, CaseDocument.DocumentType.REAL_ESTATE_CONTRACT)
        self.assertIsNotNone(real_estate_group)
        self.assertEqual(real_estate_group['items'], [])

        self.assertEqual(len(payload['report']['quote_history']), 2)
        self.assertEqual(payload['report']['quote_history'][0]['version'], 2)
        self.assertEqual(payload['report']['service_completion_forms'][0]['status'], ServiceCompletionForm.Status.REVIEWED)

    def test_customer_history_api_denies_other_customer_submission(self):
        self.client.force_login(self.customer)
        url = reverse('api_settlement_case_history_my')
        response = self.client.get(url, {'submission_id': self.other_submission.id})
        self.assertEqual(response.status_code, 404)

    def test_staff_history_api_includes_private_for_privileged_roles(self):
        self.client.force_login(self.admin)
        url = reverse('api_settlement_case_history_staff', kwargs={'submission_id': self.submission.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        real_estate_group = self._doc_group_by_type(payload, CaseDocument.DocumentType.REAL_ESTATE_CONTRACT)
        self.assertEqual(len(real_estate_group['items']), 1)
        self.assertTrue(payload['report']['acl']['can_view_private_customer_info'])

    def test_staff_history_api_excludes_private_for_non_privileged_hq_staff(self):
        self.client.force_login(self.hq_staff)
        url = reverse('api_settlement_case_history_staff', kwargs={'submission_id': self.submission.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        real_estate_group = self._doc_group_by_type(payload, CaseDocument.DocumentType.REAL_ESTATE_CONTRACT)
        self.assertEqual(real_estate_group['items'], [])
        self.assertFalse(payload['report']['acl']['can_view_private_customer_info'])

    def test_non_staff_cannot_call_staff_history_api(self):
        self.client.force_login(self.customer)
        url = reverse('api_settlement_case_history_staff', kwargs={'submission_id': self.submission.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
