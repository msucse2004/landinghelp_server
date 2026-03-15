from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile

from .document_access import create_case_document
from .models import CaseDocument, SettlementQuote
from .notifications import send_contract_package_to_customer


def _build_generated_filename(submission_id, document_type):
    return f'submission_{submission_id}_{document_type.lower()}.txt'


def _build_generated_content(submission, quote, document_type):
    lines = [
        f'Document Type: {document_type}',
        f'Submission ID: {getattr(submission, "id", "")}',
        f'Customer Email: {getattr(submission, "email", "")}',
        f'Quote ID: {getattr(quote, "id", "") if quote else ""}',
        f'Quote Total: {getattr(quote, "total", "") if quote else ""}',
    ]
    return ContentFile('\n'.join(lines).encode('utf-8'), name=_build_generated_filename(submission.id, document_type))


def create_contract_package_for_submission(submission, quote=None, generated_by=None):
    if not submission:
        raise ValueError('submission is required')

    actor = generated_by or getattr(submission, 'user', None)
    owner_user = getattr(submission, 'user', None)

    package_types = [
        CaseDocument.DocumentType.INVOICE,
        CaseDocument.DocumentType.CONSENT_FORM,
        CaseDocument.DocumentType.POWER_OF_ATTORNEY,
    ]

    created_documents = []
    for document_type in package_types:
        required_signer_roles = ['INTERNAL'] if document_type == CaseDocument.DocumentType.INVOICE else ['CUSTOMER']
        customer_action_required = document_type in {
            CaseDocument.DocumentType.CONSENT_FORM,
            CaseDocument.DocumentType.POWER_OF_ATTORNEY,
        }
        latest_same_type = (
            CaseDocument.objects.filter(
                submission=submission,
                document_type=document_type,
                metadata__package_source='QUOTE_ACCEPTANCE',
            )
            .order_by('-version', '-created_at')
            .first()
        )

        generated_file = _build_generated_content(submission, quote, document_type)
        document = create_case_document(
            submission=submission,
            uploaded_by=actor,
            file=generated_file,
            document_type=document_type,
            document_scope=CaseDocument.DocumentScope.CASE,
            visibility_level=CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
            owner_user=owner_user,
            conversation=None,
            status=CaseDocument.Status.GENERATED,
            replaces=latest_same_type,
            metadata={
                'package_source': 'QUOTE_ACCEPTANCE',
                'signature_status': 'READY_FOR_SIGNATURE',
                'customer_action_required': customer_action_required,
                'required_signer_roles': required_signer_roles,
                'generated_by_workflow': 'accept_quote',
                'quote_id': getattr(quote, 'id', None),
            },
            is_signed_final=False,
        )
        created_documents.append(document)

    return created_documents


def accept_quote(customer, quote_id=None, quote=None):
    if not customer or not getattr(customer, 'is_authenticated', False):
        raise PermissionDenied('로그인이 필요합니다.')

    role_cls = getattr(customer, 'Role', None)
    customer_role_value = getattr(role_cls, 'CUSTOMER', 'CUSTOMER')
    if getattr(customer, 'role', None) != customer_role_value:
        raise PermissionDenied('고객만 견적 수락을 진행할 수 있습니다.')

    if quote is None:
        if not quote_id:
            raise ValueError('quote_id is required')
        quote = (
            SettlementQuote.objects.filter(
                id=quote_id,
                submission__user=customer,
            )
            .select_related('submission')
            .first()
        )

    if not quote:
        raise ValueError('유효한 견적을 찾을 수 없습니다.')

    if quote.status != SettlementQuote.Status.FINAL_SENT:
        raise ValueError('송부 완료된 견적만 수락할 수 있습니다.')

    if not quote.is_payable():
        raise ValueError('수정 요청으로 무효화된 견적은 수락할 수 없습니다.')

    submission = quote.submission
    if submission.case_stage in (
        submission.CaseStage.QUOTE_ACCEPTED,
        submission.CaseStage.CONTRACT_PACKAGE_SENT,
        submission.CaseStage.CONTRACT_FULLY_SIGNED,
        submission.CaseStage.PAYMENT_COMPLETED,
        submission.CaseStage.AVAILABILITY_REQUESTED,
        submission.CaseStage.LSA_PENDING,
        submission.CaseStage.SCHEDULE_FINALIZED,
        submission.CaseStage.SERVICES_IN_PROGRESS,
        submission.CaseStage.SERVICE_COMPLETED,
        submission.CaseStage.CLOSED,
    ):
        existing_documents = list(
            CaseDocument.objects.filter(
                submission=submission,
                document_type__in=[
                    CaseDocument.DocumentType.INVOICE,
                    CaseDocument.DocumentType.CONSENT_FORM,
                    CaseDocument.DocumentType.POWER_OF_ATTORNEY,
                ],
                metadata__package_source='QUOTE_ACCEPTANCE',
            ).order_by('-created_at')
        )
        return {
            'quote': quote,
            'submission': submission,
            'documents': existing_documents,
        }

    submission.advance_case_stage(submission.CaseStage.QUOTE_ACCEPTED)

    package_documents = create_contract_package_for_submission(
        submission=submission,
        quote=quote,
        generated_by=customer,
    )
    send_contract_package_to_customer(
        submission=submission,
        documents=package_documents,
        sender=None,
    )

    return {
        'quote': quote,
        'submission': submission,
        'documents': package_documents,
    }
