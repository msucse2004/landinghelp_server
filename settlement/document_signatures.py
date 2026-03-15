from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .document_access import can_user_view_case_document, create_case_document
from .models import CaseDocument, DocumentSignature


def _required_signature_roles_for_document(document):
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    required_roles = metadata.get('required_signer_roles')
    if isinstance(required_roles, list) and required_roles:
        return [str(r).strip().upper() for r in required_roles if str(r).strip()]

    if document.document_type in {
        CaseDocument.DocumentType.CONSENT_FORM,
        CaseDocument.DocumentType.POWER_OF_ATTORNEY,
    }:
        return [DocumentSignature.SignerRole.CUSTOMER]

    if document.document_type == CaseDocument.DocumentType.INVOICE:
        return [DocumentSignature.SignerRole.INTERNAL]

    return []


def _is_customer_owner(user, submission):
    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and getattr(user, 'role', None) == getattr(getattr(user, 'Role', None), 'CUSTOMER', 'CUSTOMER')
        and getattr(submission, 'user_id', None) == getattr(user, 'id', None)
    )


def _is_internal_signer(user):
    return bool(user and getattr(user, 'is_authenticated', False) and getattr(user, 'is_internal_staff', lambda: False)())


def _signature_type_for_role(signer_role):
    if signer_role == DocumentSignature.SignerRole.CUSTOMER:
        return DocumentSignature.SignatureType.CLICK_TO_SIGN
    return DocumentSignature.SignatureType.INTERNAL_TRANSITION


def _build_signed_final_filename(submission_id):
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    return f'submission_{submission_id}_signed_final_package_{ts}.txt'


def _build_signed_final_content(submission, source_documents, signatures):
    lines = [
        'Document Type: SIGNED_FINAL_PACKAGE',
        f'Submission ID: {getattr(submission, "id", "")}',
        f'Customer Email: {getattr(submission, "email", "")}',
        f'Generated At: {timezone.now().isoformat()}',
        '',
        '[Source Documents]',
    ]
    for doc in source_documents:
        lines.append(
            f'- doc_id={doc.id} type={doc.document_type} version={doc.version} status={doc.status}'
        )

    lines.append('')
    lines.append('[Signatures]')
    for signature in signatures:
        signer_id = getattr(signature, 'signer_id', None)
        lines.append(
            f'- signature_id={signature.id} doc_id={signature.document_id} signer_role={signature.signer_role} signer_id={signer_id} signed_at={signature.signed_at.isoformat()}'
        )

    return ContentFile('\n'.join(lines).encode('utf-8'), name=_build_signed_final_filename(submission.id))


def are_required_signatures_complete(submission):
    if not submission:
        return False

    package_docs = list(
        CaseDocument.objects.filter(
            submission=submission,
            document_type__in=[
                CaseDocument.DocumentType.INVOICE,
                CaseDocument.DocumentType.CONSENT_FORM,
                CaseDocument.DocumentType.POWER_OF_ATTORNEY,
            ],
            metadata__package_source='QUOTE_ACCEPTANCE',
        ).order_by('id')
    )
    if not package_docs:
        return False

    for document in package_docs:
        required_roles = _required_signature_roles_for_document(document)
        if not required_roles:
            continue

        signed_roles = set(
            DocumentSignature.objects.filter(document=document)
            .values_list('signer_role', flat=True)
        )
        if any(role not in signed_roles for role in required_roles):
            return False

    return True


@transaction.atomic
def build_signed_final_package(submission, built_by=None):
    if not submission:
        raise ValueError('submission is required')

    existing = (
        CaseDocument.objects.filter(
            submission=submission,
            document_type=CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE,
            metadata__package_source='SIGNATURE_WORKFLOW',
        )
        .order_by('-created_at')
        .first()
    )
    if existing:
        return existing

    if not are_required_signatures_complete(submission):
        raise ValueError('필수 서명이 모두 완료되지 않았습니다.')

    source_documents = list(
        CaseDocument.objects.filter(
            submission=submission,
            document_type__in=[
                CaseDocument.DocumentType.INVOICE,
                CaseDocument.DocumentType.CONSENT_FORM,
                CaseDocument.DocumentType.POWER_OF_ATTORNEY,
            ],
            metadata__package_source='QUOTE_ACCEPTANCE',
        ).order_by('id')
    )
    if not source_documents:
        raise ValueError('계약 패키지 원본 문서를 찾을 수 없습니다.')

    signatures = list(
        DocumentSignature.objects.filter(document__in=source_documents)
        .select_related('signer', 'document')
        .order_by('signed_at', 'id')
    )

    actor = built_by or getattr(submission, 'user', None)
    if not actor or not getattr(actor, 'is_authenticated', False):
        raise ValueError('signed final package 생성 주체가 필요합니다.')

    final_file = _build_signed_final_content(submission, source_documents, signatures)
    final_package_document = create_case_document(
        submission=submission,
        uploaded_by=actor,
        file=final_file,
        document_type=CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE,
        document_scope=CaseDocument.DocumentScope.CASE,
        visibility_level=CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
        owner_user=getattr(submission, 'user', None),
        conversation=None,
        status=CaseDocument.Status.GENERATED,
        metadata={
            'package_source': 'SIGNATURE_WORKFLOW',
            'archived_server_side': True,
            'customer_delivery_required': True,
            'source_document_ids': [doc.id for doc in source_documents],
            'signature_ids': [sig.id for sig in signatures],
            'generated_by_workflow': 'build_signed_final_package',
        },
        is_signed_final=True,
    )

    for document in source_documents:
        metadata = dict(document.metadata or {})
        metadata.update({
            'signature_status': 'SIGNED',
            'signed_final_package_id': final_package_document.id,
            'signed_finalized_at': timezone.now().isoformat(),
        })
        document.metadata = metadata
        document.status = CaseDocument.Status.ARCHIVED
        document.is_signed_final = True
        document.save(update_fields=['metadata', 'status', 'is_signed_final', 'updated_at'])

    submission.advance_case_stage(submission.CaseStage.CONTRACT_FULLY_SIGNED)

    try:
        from .notifications import send_signed_final_package_delivery

        send_signed_final_package_delivery(
            submission=submission,
            final_package_document=final_package_document,
            sender=built_by,
        )
    except Exception:
        pass

    return final_package_document


@transaction.atomic
def sign_case_document(
    *,
    document,
    signer,
    signer_role=None,
    signature_type=None,
    audit_payload=None,
    ip_address=None,
    user_agent=None,
):
    if not document:
        raise ValueError('document is required')
    if not signer or not getattr(signer, 'is_authenticated', False):
        raise PermissionDenied('로그인이 필요합니다.')
    if not can_user_view_case_document(signer, document):
        raise PermissionDenied('문서 접근 권한이 없습니다.')

    expected_roles = _required_signature_roles_for_document(document)
    if not expected_roles:
        raise ValueError('해당 문서는 서명 대상이 아닙니다.')

    if signer_role:
        signer_role_value = str(signer_role).strip().upper()
    else:
        if _is_customer_owner(signer, document.submission):
            signer_role_value = DocumentSignature.SignerRole.CUSTOMER
        elif _is_internal_signer(signer):
            signer_role_value = DocumentSignature.SignerRole.INTERNAL
        else:
            signer_role_value = DocumentSignature.SignerRole.AGENT

    if signer_role_value not in expected_roles:
        raise PermissionDenied('해당 역할로는 이 문서에 서명할 수 없습니다.')

    if signer_role_value == DocumentSignature.SignerRole.CUSTOMER and not _is_customer_owner(signer, document.submission):
        raise PermissionDenied('고객 본인만 서명할 수 있습니다.')
    if signer_role_value == DocumentSignature.SignerRole.INTERNAL and not _is_internal_signer(signer):
        raise PermissionDenied('내부 담당자만 서명할 수 있습니다.')

    existing = (
        DocumentSignature.objects.filter(document=document, signer_role=signer_role_value)
        .order_by('-signed_at', '-id')
        .first()
    )
    if existing:
        return {
            'signature': existing,
            'document': document,
            'already_signed': True,
            'required_complete': are_required_signatures_complete(document.submission),
            'final_package_document': CaseDocument.objects.filter(
                submission=document.submission,
                document_type=CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE,
                metadata__package_source='SIGNATURE_WORKFLOW',
            ).order_by('-created_at').first(),
        }

    signed_at = timezone.now()
    signature = DocumentSignature.objects.create(
        document=document,
        signer=signer,
        signer_role=signer_role_value,
        signed_at=signed_at,
        signature_type=signature_type or _signature_type_for_role(signer_role_value),
        audit_payload=audit_payload or {},
        ip_address=ip_address,
        user_agent=(user_agent or '')[:1000],
    )

    metadata = dict(document.metadata or {})
    existing_roles = metadata.get('signed_roles') if isinstance(metadata.get('signed_roles'), list) else []
    signed_roles = sorted(set([str(r).strip().upper() for r in existing_roles if str(r).strip()] + [signer_role_value]))
    signature_status = 'SIGNED' if all(role in signed_roles for role in expected_roles) else 'PARTIALLY_SIGNED'
    metadata.update({
        'signed_roles': signed_roles,
        'signature_status': signature_status,
        'customer_action_required': DocumentSignature.SignerRole.CUSTOMER in [r for r in expected_roles if r not in signed_roles],
        'last_signature_id': signature.id,
        'last_signed_at': signed_at.isoformat(),
    })
    document.metadata = metadata
    document.is_signed_final = signature_status == 'SIGNED'
    document.save(update_fields=['metadata', 'is_signed_final', 'updated_at'])

    required_complete = are_required_signatures_complete(document.submission)
    final_package_document = None
    if required_complete:
        final_package_document = build_signed_final_package(document.submission, built_by=signer)

    return {
        'signature': signature,
        'document': document,
        'already_signed': False,
        'required_complete': required_complete,
        'final_package_document': final_package_document,
    }
