from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from settlement.document_access import can_user_view_case_document, documents_visible_to_user_queryset
from settlement.models import CaseDocument
from survey.models import SurveySubmission


User = get_user_model()


class CaseDocumentVisibilityPolicyTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username='doc_super_admin',
            email='doc_super_admin@test.com',
            password='pass1234',
            role=User.Role.SUPER_ADMIN,
            is_superuser=True,
            is_staff=True,
        )
        self.admin = User.objects.create_user(
            username='doc_admin',
            email='doc_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.supervisor = User.objects.create_user(
            username='doc_supervisor',
            email='doc_supervisor@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
            is_staff=True,
        )
        self.hq_staff = User.objects.create_user(
            username='doc_hq_staff',
            email='doc_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='doc_customer_owner',
            email='doc_customer_owner@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='doc_customer_other',
            email='doc_customer_other@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )

        self.submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
        )

        self.private_customer_doc = self._create_doc(
            CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
            'private_customer.pdf',
        )
        self.private_financial_doc = self._create_doc(
            CaseDocument.VisibilityLevel.PRIVATE_FINANCIAL,
            'private_financial.pdf',
        )
        self.internal_doc = self._create_doc(
            CaseDocument.VisibilityLevel.INTERNAL_GENERAL,
            'internal.pdf',
        )
        self.shared_doc = self._create_doc(
            CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
            'shared.pdf',
        )
        self.agent = User.objects.create_user(
            username='doc_agent_owner',
            email='doc_agent_owner@test.com',
            password='pass1234',
            role=User.Role.AGENT,
        )
        self.agent_identity_doc = CaseDocument.objects.create(
            submission=self.submission,
            document_type=CaseDocument.DocumentType.AGENT_ID_FRONT,
            document_scope=CaseDocument.DocumentScope.CASE,
            visibility_level=CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
            uploaded_by=self.agent,
            owner_user=self.agent,
            file=SimpleUploadedFile('agent_id_front.pdf', b'dummy', content_type='application/pdf'),
            original_filename='agent_id_front.pdf',
            status=CaseDocument.Status.UPLOADED,
            metadata={'identity_verification_document': True},
        )

    def _create_doc(self, visibility_level, filename):
        return CaseDocument.objects.create(
            submission=self.submission,
            document_type=CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT,
            document_scope=CaseDocument.DocumentScope.CASE,
            visibility_level=visibility_level,
            uploaded_by=self.customer,
            owner_user=self.customer,
            file=SimpleUploadedFile(filename, b'dummy', content_type='application/pdf'),
            original_filename=filename,
            status=CaseDocument.Status.UPLOADED,
        )

    def test_private_customer_visibility_is_strictly_restricted(self):
        self.assertTrue(can_user_view_case_document(self.customer, self.private_customer_doc))
        self.assertTrue(can_user_view_case_document(self.super_admin, self.private_customer_doc))
        self.assertTrue(can_user_view_case_document(self.admin, self.private_customer_doc))
        self.assertTrue(can_user_view_case_document(self.supervisor, self.private_customer_doc))

        self.assertFalse(can_user_view_case_document(self.hq_staff, self.private_customer_doc))
        self.assertFalse(can_user_view_case_document(self.other_customer, self.private_customer_doc))

    def test_hq_staff_queryset_excludes_private_customer_and_financial(self):
        doc_ids = set(documents_visible_to_user_queryset(self.hq_staff).values_list('id', flat=True))

        self.assertIn(self.internal_doc.id, doc_ids)
        self.assertIn(self.shared_doc.id, doc_ids)
        self.assertNotIn(self.private_customer_doc.id, doc_ids)
        self.assertNotIn(self.private_financial_doc.id, doc_ids)
        self.assertNotIn(self.agent_identity_doc.id, doc_ids)

    def test_agent_identity_docs_are_visible_only_to_privileged_staff(self):
        self.assertTrue(can_user_view_case_document(self.super_admin, self.agent_identity_doc))
        self.assertTrue(can_user_view_case_document(self.admin, self.agent_identity_doc))
        self.assertTrue(can_user_view_case_document(self.supervisor, self.agent_identity_doc))
        self.assertFalse(can_user_view_case_document(self.hq_staff, self.agent_identity_doc))
        self.assertFalse(can_user_view_case_document(self.customer, self.agent_identity_doc))
        self.assertFalse(can_user_view_case_document(self.agent, self.agent_identity_doc))

    def test_detail_api_enforces_private_customer_access(self):
        detail_url = reverse('api_settlement_case_document_detail', kwargs={'document_id': self.private_customer_doc.id})

        self.client.force_login(self.hq_staff)
        denied_response = self.client.get(detail_url)
        self.assertEqual(denied_response.status_code, 403)

        self.client.force_login(self.admin)
        allowed_response = self.client.get(detail_url)
        self.assertEqual(allowed_response.status_code, 200)
        self.assertTrue(allowed_response.json().get('ok'))

    def test_customer_upload_and_list_api(self):
        self.client.force_login(self.customer)

        list_url = reverse('api_settlement_case_documents')
        upload_file = SimpleUploadedFile('customer_new.pdf', b'new-content', content_type='application/pdf')
        upload_response = self.client.post(
            list_url,
            {
                'submission_id': self.submission.id,
                'document_type': CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT,
                'visibility_level': CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
                'file': upload_file,
            },
        )
        self.assertEqual(upload_response.status_code, 201)

        list_response = self.client.get(list_url, {'submission_id': self.submission.id})
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertTrue(payload.get('ok'))
        self.assertGreaterEqual(len(payload.get('documents', [])), 1)
