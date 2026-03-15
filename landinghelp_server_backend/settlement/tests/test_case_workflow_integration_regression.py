import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from messaging.models import Conversation
from settlement.document_access import can_user_view_case_document
from settlement.document_signatures import sign_case_document
from settlement.lsa_service import build_lsa_response_token, send_lsa_batch_for_schedule_plan
from settlement.models import (
    AvailabilityRequest,
    CaseDocument,
    LsaAgentRequest,
    ServiceCompletionForm,
    ServiceScheduleItem,
    ServiceSchedulePlan,
    SettlementQuote,
    UserSettlementPlan,
)
from settlement.quote_acceptance import accept_quote
from settlement.quote_approval import finalize_and_send_quote
from settlement.quote_checkout import process_quote_payment
from survey.models import SurveySubmission


User = get_user_model()


class CaseWorkflowIntegrationRegressionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='it_admin',
            email='it_admin@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
            is_staff=True,
        )
        self.supervisor = User.objects.create_user(
            username='it_supervisor',
            email='it_supervisor@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
            is_staff=True,
        )
        self.hq_staff = User.objects.create_user(
            username='it_hq_staff',
            email='it_hq_staff@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            username='it_customer',
            email='it_customer@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='it_agent',
            email='it_agent@test.com',
            password='pass1234',
            role=User.Role.AGENT,
            status=User.Status.ACTIVE,
            agent_states=['NC'],
        )

    @patch('settlement.scheduling_engine.ensure_submission_schedule_draft', return_value=(None, False))
    @patch('settlement.post_payment.ensure_plan_service_tasks')
    @patch('settlement.notifications.send_schedule_sent_to_customer', return_value=True)
    def test_e2e_case_workflow_regression_and_acl_invariants(
        self,
        _mock_schedule_notice,
        _mock_post_payment_tasks,
        _mock_schedule_draft,
    ):
        # Invariant 1: customer survey submission starts the case pipeline at SUBMITTED.
        submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            case_stage=SurveySubmission.CaseStage.SURVEY_IN_PROGRESS,
            requested_required_services=['SVC_FULL_E2E'],
            answers={
                'region': 'North Carolina',
                'service_delivery_per_service': {'SVC_FULL_E2E': 'agent_direct'},
            },
        )

        # A review-stage plan exists before payment and later LSA/schedule actions reuse it.
        review_plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.REVIEWING,
            source=ServiceSchedulePlan.Source.ADMIN,
            version=1,
            created_by=self.admin,
            updated_by=self.admin,
        )
        future_start = timezone.now() + timedelta(days=2)
        ServiceScheduleItem.objects.create(
            schedule_plan=review_plan,
            service_code='SVC_FULL_E2E',
            service_label='Full E2E Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=future_start,
            ends_at=future_start + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.SCHEDULED,
        )

        # Invariant 2: only authorized internal actor sends quote.
        quote = SettlementQuote.objects.create(
            submission=submission,
            status=SettlementQuote.Status.DRAFT,
            version=1,
            total=Decimal('1999.00'),
            items=[{'code': 'SVC_FULL_E2E', 'label': 'Full E2E Service', 'price': 1999}],
        )
        finalize_and_send_quote(quote, actor=self.admin)
        quote.refresh_from_db()
        submission.refresh_from_db()
        self.assertEqual(quote.status, SettlementQuote.Status.FINAL_SENT)
        self.assertEqual(submission.case_stage, SurveySubmission.CaseStage.QUOTE_SENT)

        # Invariant 3~4: customer accepts quote; contract package is generated but quote remains unpaid.
        accept_result = accept_quote(self.customer, quote_id=quote.id)
        submission.refresh_from_db()
        quote.refresh_from_db()
        self.assertEqual(submission.case_stage, SurveySubmission.CaseStage.QUOTE_ACCEPTED)
        self.assertEqual(quote.status, SettlementQuote.Status.FINAL_SENT)
        self.assertEqual(len(accept_result.get('documents') or []), 3)

        package_docs = list(
            CaseDocument.objects.filter(
                submission=submission,
                document_type__in=[
                    CaseDocument.DocumentType.INVOICE,
                    CaseDocument.DocumentType.CONSENT_FORM,
                    CaseDocument.DocumentType.POWER_OF_ATTORNEY,
                ],
                metadata__package_source='QUOTE_ACCEPTANCE',
            )
        )
        self.assertEqual(len(package_docs), 3)

        # Invariant 5~6: required signatures complete and signed final package is archived.
        invoice = next(doc for doc in package_docs if doc.document_type == CaseDocument.DocumentType.INVOICE)
        consent = next(doc for doc in package_docs if doc.document_type == CaseDocument.DocumentType.CONSENT_FORM)
        poa = next(doc for doc in package_docs if doc.document_type == CaseDocument.DocumentType.POWER_OF_ATTORNEY)

        sign_case_document(document=consent, signer=self.customer)
        sign_case_document(document=poa, signer=self.customer)
        sign_result = sign_case_document(document=invoice, signer=self.admin)

        final_package = sign_result.get('final_package_document')
        self.assertIsNotNone(final_package)
        self.assertEqual(final_package.document_type, CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE)
        submission.refresh_from_db()
        self.assertEqual(submission.case_stage, SurveySubmission.CaseStage.CONTRACT_FULLY_SIGNED)

        for doc in package_docs:
            doc.refresh_from_db()
            self.assertEqual(doc.status, CaseDocument.Status.ARCHIVED)
            self.assertEqual((doc.metadata or {}).get('signature_status'), 'SIGNED')

        # Invariant 7~8: payment completes after signatures and creates internal availability requests.
        UserSettlementPlan.objects.create(
            user=self.customer,
            assigned_agent=self.agent,
            state='NC',
            city='Charlotte',
            checkout_total=Decimal('1999.00'),
        )
        paid_quote, payment_error = process_quote_payment(self.customer, quote_id=quote.id)
        self.assertIsNone(payment_error)
        self.assertIsNotNone(paid_quote)

        submission.refresh_from_db()
        quote.refresh_from_db()
        self.assertEqual(quote.status, SettlementQuote.Status.PAID)
        self.assertEqual(submission.case_stage, SurveySubmission.CaseStage.PAYMENT_COMPLETED)

        availability_requests = AvailabilityRequest.objects.filter(submission=submission)
        self.assertEqual(availability_requests.count(), 2)
        self.assertEqual(
            set(availability_requests.values_list('participant_role', flat=True)),
            {AvailabilityRequest.ParticipantRole.CUSTOMER, AvailabilityRequest.ParticipantRole.AGENT},
        )

        # Invariant 9: first-time agent must upload ID docs before LSA response is accepted.
        self.agent.agent_identity_verification_status = User.AgentIdentityVerificationStatus.REQUIRED
        self.agent.save(update_fields=['agent_identity_verification_status'])

        batch, requests = send_lsa_batch_for_schedule_plan(review_plan, [self.agent], actor=self.admin)
        lsa_request = requests[0]
        token = build_lsa_response_token(lsa_request.id, self.agent.id)
        proposed = batch.proposed_schedule_snapshot[0]

        self.client.force_login(self.agent)
        lsa_submit_url = reverse('agent_lsa_response_submit', kwargs={'request_id': lsa_request.id})
        denied = self.client.post(
            lsa_submit_url,
            data={
                'token': token,
                'decision': 'ACCEPT_AS_IS',
                'note': 'missing docs',
                'items': json.dumps([{
                    'service_code': proposed['service_code'],
                    'service_label': proposed['service_label'],
                    'proposed_starts_at': proposed['starts_at'],
                    'proposed_ends_at': proposed['ends_at'],
                    'action': 'ACCEPT',
                }]),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(denied.json().get('error'), 'identity_documents_required')

        allowed = self.client.post(
            lsa_submit_url,
            data={
                'token': token,
                'decision': 'ACCEPT_AS_IS',
                'note': 'with docs',
                'items': json.dumps([{
                    'service_code': proposed['service_code'],
                    'service_label': proposed['service_label'],
                    'proposed_starts_at': proposed['starts_at'],
                    'proposed_ends_at': proposed['ends_at'],
                    'action': 'ACCEPT',
                }]),
                'id_front': SimpleUploadedFile('front.png', b'front-bytes', content_type='image/png'),
                'id_back': SimpleUploadedFile('back.png', b'back-bytes', content_type='image/png'),
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(allowed.status_code, 200)
        lsa_request.refresh_from_db()
        self.assertEqual(lsa_request.status, LsaAgentRequest.Status.RESPONDED)

        # Invariant 10: only authorized role can finalize schedule.
        submission.advance_case_stage(SurveySubmission.CaseStage.LSA_PENDING)
        finalize_url = reverse('app_submission_review_schedule_finalize', kwargs={'submission_id': submission.id})

        self.client.force_login(self.hq_staff)
        denied_finalize = self.client.post(finalize_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(denied_finalize.status_code, 403)

        self.client.force_login(self.supervisor)
        allowed_finalize = self.client.post(finalize_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(allowed_finalize.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.case_stage, SurveySubmission.CaseStage.SCHEDULE_FINALIZED)

        # Invariant 11: both workspace threads must exist per submission.
        workspace_types = set(
            Conversation.objects.filter(survey_submission=submission).values_list('workspace_type', flat=True)
        )
        self.assertIn(Conversation.WorkspaceType.HQ_BACKOFFICE, workspace_types)
        self.assertIn(Conversation.WorkspaceType.LOCAL_EXECUTION, workspace_types)

        # Invariant 12: document ACL blocks HQ_STAFF from PRIVATE_CUSTOMER docs.
        private_doc = CaseDocument.objects.create(
            submission=submission,
            document_type=CaseDocument.DocumentType.REAL_ESTATE_CONTRACT,
            document_scope=CaseDocument.DocumentScope.CASE,
            visibility_level=CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
            uploaded_by=self.admin,
            owner_user=self.customer,
            file=SimpleUploadedFile('private_customer.pdf', b'dummy', content_type='application/pdf'),
            original_filename='private_customer.pdf',
            status=CaseDocument.Status.UPLOADED,
        )
        self.assertFalse(can_user_view_case_document(self.hq_staff, private_doc))
        self.assertTrue(can_user_view_case_document(self.customer, private_doc))
        self.assertTrue(can_user_view_case_document(self.admin, private_doc))

        self.client.force_login(self.hq_staff)
        detail_url = reverse('api_settlement_case_document_detail', kwargs={'document_id': private_doc.id})
        detail_denied = self.client.get(detail_url)
        self.assertEqual(detail_denied.status_code, 403)

        # Invariant 13: assigned agent can submit service completion after all assigned work ends.
        execution_plan = ServiceSchedulePlan.objects.create(
            submission=submission,
            customer=self.customer,
            status=ServiceSchedulePlan.Status.ACTIVE,
            source=ServiceSchedulePlan.Source.HYBRID,
            version=2,
            created_by=self.admin,
            updated_by=self.admin,
        )
        past_start = timezone.now() - timedelta(hours=3)
        ServiceScheduleItem.objects.create(
            schedule_plan=execution_plan,
            service_code='SVC_EXEC_DONE',
            service_label='Execution Done Service',
            service_type=ServiceScheduleItem.ServiceType.IN_PERSON_AGENT,
            starts_at=past_start,
            ends_at=past_start + timedelta(hours=1),
            duration_minutes=60,
            assigned_agent=self.agent,
            status=ServiceScheduleItem.ItemStatus.CONFIRMED,
        )

        self.client.force_login(self.agent)
        completion_submit_url = reverse('api_settlement_service_completion_submit')
        submit_completion = self.client.post(
            completion_submit_url,
            data=json.dumps({
                'submission_id': submission.id,
                'schedule_plan_id': execution_plan.id,
                'summary': 'all done',
                'completion_notes': 'everything complete',
                'attachments_count': 1,
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(submit_completion.status_code, 200)
        completion_form_id = submit_completion.json()['form']['id']

        # Review completion so customer history includes it under customer-shared rules.
        self.client.force_login(self.admin)
        completion_review_url = reverse('api_settlement_service_completion_review', kwargs={'form_id': completion_form_id})
        review_completion = self.client.post(completion_review_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(review_completion.status_code, 200)

        form = ServiceCompletionForm.objects.get(id=completion_form_id)
        self.assertEqual(form.status, ServiceCompletionForm.Status.REVIEWED)

        # Invariant 14: customer history must aggregate grouped docs and reviewed completion forms.
        self.client.force_login(self.customer)
        history_url = reverse('api_settlement_case_history_my')
        history_response = self.client.get(history_url, {'submission_id': submission.id})
        self.assertEqual(history_response.status_code, 200)
        payload = history_response.json()['report']

        groups = {group['document_type']: group['items'] for group in payload['document_groups']}
        self.assertGreaterEqual(len(groups.get(CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE, [])), 1)
        self.assertGreaterEqual(len(payload.get('quote_history', [])), 1)
        self.assertGreaterEqual(len(payload.get('service_completion_forms', [])), 1)
