from django.core.exceptions import PermissionDenied

from survey.models import SurveySubmission

from .document_access import documents_visible_to_user_queryset
from .models import CaseDocument, ServiceCompletionForm, SettlementQuote


REPORT_DOCUMENT_TYPES = (
    CaseDocument.DocumentType.QUOTE,
    CaseDocument.DocumentType.INVOICE,
    CaseDocument.DocumentType.CONSENT_FORM,
    CaseDocument.DocumentType.POWER_OF_ATTORNEY,
    CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE,
    CaseDocument.DocumentType.REAL_ESTATE_CONTRACT,
    CaseDocument.DocumentType.UTILITY_CONFIRMATION,
    CaseDocument.DocumentType.CUSTOMER_REQUESTED_DOCUMENT,
    CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT,
    CaseDocument.DocumentType.SERVICE_COMPLETION_FORM,
)

REPORT_DOCUMENT_GROUP_ORDER = (
    CaseDocument.DocumentType.QUOTE,
    CaseDocument.DocumentType.INVOICE,
    CaseDocument.DocumentType.CONSENT_FORM,
    CaseDocument.DocumentType.POWER_OF_ATTORNEY,
    CaseDocument.DocumentType.SIGNED_FINAL_PACKAGE,
    CaseDocument.DocumentType.REAL_ESTATE_CONTRACT,
    CaseDocument.DocumentType.UTILITY_CONFIRMATION,
    CaseDocument.DocumentType.CUSTOMER_REQUESTED_DOCUMENT,
    CaseDocument.DocumentType.CUSTOMER_UPLOADED_DOCUMENT,
    CaseDocument.DocumentType.SERVICE_COMPLETION_FORM,
)


def _is_internal_staff(user):
    return bool(user and getattr(user, 'is_authenticated', False) and getattr(user, 'is_internal_staff', lambda: False)())


def _is_customer_owner(user, submission):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return bool(getattr(submission, 'user_id', None) and submission.user_id == user.id)


def _is_privileged_private_customer_viewer(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    role = getattr(user, 'role', None)
    role_cls = getattr(user, 'Role', None)
    allowed_roles = {
        getattr(role_cls, 'SUPER_ADMIN', 'SUPER_ADMIN'),
        getattr(role_cls, 'ADMIN', 'ADMIN'),
        getattr(role_cls, 'SUPERVISOR', 'SUPERVISOR'),
    }
    return bool(getattr(user, 'is_superuser', False) or role in allowed_roles)


def can_user_access_case_history_submission(user, submission):
    if not user or not getattr(user, 'is_authenticated', False) or not submission:
        return False
    if _is_internal_staff(user):
        return True
    return _is_customer_owner(user, submission)


def _serialize_quote(quote):
    return {
        'id': quote.id,
        'status': quote.status,
        'status_label': quote.get_status_display(),
        'version': quote.version,
        'total': float(quote.total or 0),
        'region': quote.region or '',
        'sent_at': quote.sent_at.isoformat() if quote.sent_at else '',
        'created_at': quote.created_at.isoformat() if quote.created_at else '',
        'updated_at': quote.updated_at.isoformat() if quote.updated_at else '',
    }


def _serialize_case_document(document):
    file_url = ''
    try:
        if document.file:
            file_url = document.file.url
    except Exception:
        file_url = ''

    return {
        'id': document.id,
        'document_type': document.document_type,
        'document_type_label': document.get_document_type_display(),
        'visibility_level': document.visibility_level,
        'status': document.status,
        'version': document.version,
        'original_filename': document.original_filename,
        'file_url': file_url,
        'metadata': document.metadata or {},
        'created_at': document.created_at.isoformat() if document.created_at else '',
        'updated_at': document.updated_at.isoformat() if document.updated_at else '',
    }


def _serialize_service_completion_form(form):
    return {
        'id': form.id,
        'status': form.status,
        'status_label': form.get_status_display(),
        'summary': form.summary,
        'completion_notes': form.completion_notes,
        'attachments_count': form.attachments_count,
        'submitted_at': form.submitted_at.isoformat() if form.submitted_at else '',
        'reviewed_at': form.reviewed_at.isoformat() if form.reviewed_at else '',
        'agent_id': form.agent_id,
        'agent_name': (form.agent.get_full_name() or form.agent.username or form.agent.email or '') if form.agent_id else '',
        'schedule_plan_id': form.schedule_plan_id,
    }


def _group_documents_by_type(documents):
    grouped = {key: [] for key in REPORT_DOCUMENT_GROUP_ORDER}
    for document in documents:
        grouped.setdefault(document.document_type, []).append(document)

    out = []
    for key in REPORT_DOCUMENT_GROUP_ORDER:
        rows = grouped.get(key) or []
        rows.sort(key=lambda row: (row.version or 0, row.created_at), reverse=True)
        out.append({
            'document_type': key,
            'document_type_label': dict(CaseDocument.DocumentType.choices).get(key, key),
            'items': [_serialize_case_document(row) for row in rows],
        })
    return out


def build_case_history_report(user, submission, *, customer_shared_only=False):
    if not can_user_access_case_history_submission(user, submission):
        raise PermissionDenied('케이스 히스토리를 조회할 권한이 없습니다.')

    visible_documents_qs = documents_visible_to_user_queryset(user).filter(
        submission=submission,
        document_type__in=REPORT_DOCUMENT_TYPES,
    )

    if customer_shared_only:
        visible_documents_qs = visible_documents_qs.filter(
            visibility_level=CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
        )

    documents = list(visible_documents_qs)

    quotes = list(
        SettlementQuote.objects.filter(submission=submission)
        .order_by('-version', '-updated_at', '-id')
    )

    service_completion_qs = ServiceCompletionForm.objects.filter(submission=submission).select_related('agent').order_by('-submitted_at', '-id')
    if customer_shared_only:
        service_completion_qs = service_completion_qs.filter(status=ServiceCompletionForm.Status.REVIEWED)
    service_completion_forms = list(service_completion_qs)

    can_view_private_customer_info = bool(
        _is_customer_owner(user, submission) or _is_privileged_private_customer_viewer(user)
    )

    return {
        'submission_id': submission.id,
        'case_stage': getattr(submission, 'case_stage', ''),
        'submission_status': getattr(submission, 'status', ''),
        'access_scope': 'CUSTOMER_SHARED_ONLY' if customer_shared_only else 'DEFAULT_ROLE_SCOPE',
        'acl': {
            'can_view_private_customer_info': can_view_private_customer_info,
            'private_customer_info_allowed_roles': ['CUSTOMER', 'SUPER_ADMIN', 'ADMIN', 'SUPERVISOR'],
        },
        'quote_history': [_serialize_quote(row) for row in quotes],
        'document_groups': _group_documents_by_type(documents),
        'service_completion_forms': [_serialize_service_completion_form(row) for row in service_completion_forms],
    }


def resolve_customer_submission_for_history(user, submission_id=None):
    if not user or not getattr(user, 'is_authenticated', False):
        return None

    qs = SurveySubmission.objects.filter(user=user)
    if submission_id is not None:
        try:
            submission_id_int = int(submission_id)
        except (TypeError, ValueError):
            return None
        return qs.filter(id=submission_id_int).first()

    return qs.exclude(status=SurveySubmission.Status.DRAFT).order_by('-updated_at').first()
