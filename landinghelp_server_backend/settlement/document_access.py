from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import AgentAppointmentRequest, CaseDocument, LsaAgentContract, ServiceScheduleItem


RESTRICTED_AGENT_IDENTITY_DOCUMENT_TYPES = {
    CaseDocument.DocumentType.AGENT_ID_FRONT,
    CaseDocument.DocumentType.AGENT_ID_BACK,
}


def _is_internal_staff(user):
    return bool(getattr(user, 'is_authenticated', False) and getattr(user, 'is_internal_staff', lambda: False)())


def _is_customer_owner(user, submission, owner_user_id=None):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if owner_user_id and user.id == owner_user_id:
        return True
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


def _is_agent_related_to_submission(user, submission):
    if not user or not submission:
        return False
    role_cls = getattr(user, 'Role', None)
    if getattr(user, 'role', None) != getattr(role_cls, 'AGENT', 'AGENT'):
        return False

    customer_id = getattr(submission, 'user_id', None)
    if customer_id and AgentAppointmentRequest.objects.filter(customer_id=customer_id, agent_id=user.id).exists():
        return True

    if ServiceScheduleItem.objects.filter(schedule_plan__submission=submission, assigned_agent_id=user.id).exists():
        return True

    if LsaAgentContract.objects.filter(submission=submission, selected_agent_id=user.id).exists():
        return True

    return False


def can_user_view_case_document(user, case_document):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not case_document or not getattr(case_document, 'submission_id', None):
        return False

    submission = case_document.submission
    owner_user_id = getattr(case_document, 'owner_user_id', None)
    visibility = case_document.visibility_level

    if case_document.document_type in RESTRICTED_AGENT_IDENTITY_DOCUMENT_TYPES:
        return _is_privileged_private_customer_viewer(user)

    if visibility == CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER:
        return _is_customer_owner(user, submission, owner_user_id=owner_user_id) or _is_privileged_private_customer_viewer(user)

    if visibility == CaseDocument.VisibilityLevel.PRIVATE_FINANCIAL:
        return _is_customer_owner(user, submission, owner_user_id=owner_user_id) or _is_privileged_private_customer_viewer(user)

    if visibility == CaseDocument.VisibilityLevel.INTERNAL_GENERAL:
        return _is_internal_staff(user)

    if visibility == CaseDocument.VisibilityLevel.LOCAL_EXECUTION:
        if _is_customer_owner(user, submission, owner_user_id=owner_user_id):
            return True
        if _is_internal_staff(user):
            return True
        return _is_agent_related_to_submission(user, submission)

    if visibility == CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER:
        if _is_customer_owner(user, submission, owner_user_id=owner_user_id):
            return True
        if _is_internal_staff(user):
            return True
        return _is_agent_related_to_submission(user, submission)

    return False


def can_user_upload_case_document(user, submission, visibility_level, owner_user=None):
    if not user or not getattr(user, 'is_authenticated', False) or not submission:
        return False

    if getattr(user, 'can_manage_case_documents', lambda: False)():
        return True

    role_cls = getattr(user, 'Role', None)
    is_customer = getattr(user, 'role', None) == getattr(role_cls, 'CUSTOMER', 'CUSTOMER')
    if not is_customer:
        return False

    if getattr(submission, 'user_id', None) != user.id:
        return False

    if owner_user and getattr(owner_user, 'id', None) != user.id:
        return False

    return visibility_level in {
        CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
        CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
        CaseDocument.VisibilityLevel.LOCAL_EXECUTION,
    }


def documents_visible_to_user_queryset(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return CaseDocument.objects.none()

    role_cls = getattr(user, 'Role', None)
    is_customer = getattr(user, 'role', None) == getattr(role_cls, 'CUSTOMER', 'CUSTOMER')

    if _is_privileged_private_customer_viewer(user):
        return CaseDocument.objects.all().select_related('submission', 'owner_user', 'uploaded_by', 'conversation')

    if _is_internal_staff(user):
        return CaseDocument.objects.exclude(
            Q(visibility_level__in=[
                CaseDocument.VisibilityLevel.PRIVATE_CUSTOMER,
                CaseDocument.VisibilityLevel.PRIVATE_FINANCIAL,
            ])
            | Q(document_type__in=RESTRICTED_AGENT_IDENTITY_DOCUMENT_TYPES)
        ).select_related('submission', 'owner_user', 'uploaded_by', 'conversation')

    if is_customer:
        return CaseDocument.objects.filter(
            Q(owner_user_id=user.id) | Q(submission__user_id=user.id)
        ).exclude(
            document_type__in=RESTRICTED_AGENT_IDENTITY_DOCUMENT_TYPES
        ).select_related('submission', 'owner_user', 'uploaded_by', 'conversation')

    if getattr(user, 'role', None) == getattr(role_cls, 'AGENT', 'AGENT'):
        from survey.models import SurveySubmission

        appointment_customer_ids = list(
            AgentAppointmentRequest.objects.filter(agent_id=user.id, customer_id__isnull=False)
            .values_list('customer_id', flat=True)
            .distinct()
        )
        submission_ids = set(
            SurveySubmission.objects.filter(user_id__in=appointment_customer_ids)
            .values_list('id', flat=True)
        )
        submission_ids.update(
            ServiceScheduleItem.objects.filter(assigned_agent_id=user.id)
            .values_list('schedule_plan__submission_id', flat=True)
        )
        submission_ids.update(
            LsaAgentContract.objects.filter(selected_agent_id=user.id)
            .values_list('submission_id', flat=True)
        )
        submission_ids = [sid for sid in submission_ids if sid]
        if not submission_ids:
            return CaseDocument.objects.none()
        return CaseDocument.objects.filter(
            submission_id__in=submission_ids,
            visibility_level__in=[
                CaseDocument.VisibilityLevel.LOCAL_EXECUTION,
                CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
            ],
        ).exclude(
            document_type__in=RESTRICTED_AGENT_IDENTITY_DOCUMENT_TYPES
        ).select_related('submission', 'owner_user', 'uploaded_by', 'conversation')

    return CaseDocument.objects.none()


def create_case_document(
    *,
    submission,
    uploaded_by,
    file,
    document_type,
    document_scope=CaseDocument.DocumentScope.CASE,
    visibility_level=CaseDocument.VisibilityLevel.SHARED_WITH_CUSTOMER,
    owner_user=None,
    conversation=None,
    status=CaseDocument.Status.UPLOADED,
    replaces=None,
    metadata=None,
    is_signed_final=False,
):
    if not can_user_upload_case_document(uploaded_by, submission, visibility_level, owner_user=owner_user):
        raise PermissionDenied('문서를 업로드할 권한이 없습니다.')

    if owner_user is None:
        owner_user = getattr(submission, 'user', None)

    version = 1
    if replaces is not None:
        version = (getattr(replaces, 'version', 0) or 0) + 1
    else:
        latest = (
            CaseDocument.objects.filter(submission=submission, document_type=document_type)
            .order_by('-version')
            .only('version')
            .first()
        )
        if latest:
            version = (latest.version or 0) + 1

    original_filename = getattr(file, 'name', '') or ''

    return CaseDocument.objects.create(
        submission=submission,
        conversation=conversation,
        document_type=document_type,
        document_scope=document_scope,
        visibility_level=visibility_level,
        uploaded_by=uploaded_by,
        owner_user=owner_user,
        file=file,
        original_filename=original_filename[:255],
        status=status,
        version=version,
        replaces=replaces,
        metadata=metadata or {},
        is_signed_final=bool(is_signed_final),
    )
