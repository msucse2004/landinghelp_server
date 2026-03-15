from django.contrib.auth import get_user_model
from django.db import models, transaction

from .models import Conversation, ConversationParticipant


def _customer_display_name(submission):
    customer = getattr(submission, 'user', None)
    if customer and getattr(customer, 'is_authenticated', True):
        return (
            (getattr(customer, 'get_full_name', lambda: '')() or '').strip()
            or (getattr(customer, 'username', None) or '').strip()
            or (getattr(customer, 'email', None) or '').strip()
            or (getattr(submission, 'email', None) or '').strip()
            or '-'
        )
    return (getattr(submission, 'email', None) or '').strip() or '-'


def _hq_subject(submission):
    return f"[{_customer_display_name(submission)}] 본사업무방"


def _local_subject(submission):
    return f"[{_customer_display_name(submission)}] 현지진행방"


def _internal_staff_users():
    User = get_user_model()
    role_values = ()
    if hasattr(User, 'internal_staff_role_values'):
        role_values = tuple(User.internal_staff_role_values())
    base_q = models.Q(is_staff=True) | models.Q(is_superuser=True)
    if role_values:
        base_q = base_q | models.Q(role__in=role_values)
    return User.objects.filter(base_q, is_active=True).distinct()


def _collect_local_agent_ids(submission, extra_agent=None):
    out = set()
    if extra_agent is not None:
        extra_id = getattr(extra_agent, 'id', None)
        if extra_id:
            out.add(extra_id)

    customer = getattr(submission, 'user', None)
    customer_id = getattr(customer, 'id', None)
    try:
        from settlement.models import AgentAppointmentRequest

        if customer_id:
            for aid in AgentAppointmentRequest.objects.filter(customer_id=customer_id).exclude(agent_id__isnull=True).values_list('agent_id', flat=True):
                if aid:
                    out.add(aid)
    except Exception:
        pass

    try:
        from settlement.models import ServiceScheduleItem

        for aid in ServiceScheduleItem.objects.filter(
            schedule_plan__submission=submission,
            assigned_agent_id__isnull=False,
        ).values_list('assigned_agent_id', flat=True):
            if aid:
                out.add(aid)
    except Exception:
        pass

    try:
        from settlement.models import LsaAgentContract

        for aid in LsaAgentContract.objects.filter(submission=submission).exclude(selected_agent_id__isnull=True).values_list('selected_agent_id', flat=True):
            if aid:
                out.add(aid)
    except Exception:
        pass

    return out


def _sync_workspace_participants_for_conversation(conversation, submission, extra_agent=None):
    customer = getattr(submission, 'user', None)
    customer_id = getattr(customer, 'id', None)
    internal_staff_ids = list(_internal_staff_users().values_list('id', flat=True))

    target_ids = set(internal_staff_ids)
    if customer_id:
        target_ids.add(customer_id)

    if conversation.workspace_type == Conversation.WorkspaceType.LOCAL_EXECUTION:
        target_ids.update(_collect_local_agent_ids(submission, extra_agent=extra_agent))

    existing_ids = set(
        ConversationParticipant.objects.filter(conversation=conversation).values_list('user_id', flat=True)
    )

    missing_ids = [uid for uid in target_ids if uid not in existing_ids]
    for uid in missing_ids:
        ConversationParticipant.objects.get_or_create(conversation=conversation, user_id=uid)


@transaction.atomic
def get_or_create_hq_workspace(submission):
    if not submission:
        raise ValueError('submission is required')

    conversation, _created = Conversation.objects.get_or_create(
        survey_submission=submission,
        workspace_type=Conversation.WorkspaceType.HQ_BACKOFFICE,
        defaults={
            'type': Conversation.Type.NOTICE,
            'subject': _hq_subject(submission),
        },
    )
    desired_subject = _hq_subject(submission)
    updates = []
    if conversation.type != Conversation.Type.NOTICE:
        conversation.type = Conversation.Type.NOTICE
        updates.append('type')
    if conversation.subject != desired_subject:
        conversation.subject = desired_subject
        updates.append('subject')
    if updates:
        conversation.save(update_fields=updates)

    _sync_workspace_participants_for_conversation(conversation, submission)
    return conversation


@transaction.atomic
def get_or_create_local_workspace(submission, agent=None):
    if not submission:
        raise ValueError('submission is required')

    conversation, _created = Conversation.objects.get_or_create(
        survey_submission=submission,
        workspace_type=Conversation.WorkspaceType.LOCAL_EXECUTION,
        defaults={
            'type': Conversation.Type.NOTICE,
            'subject': _local_subject(submission),
        },
    )
    desired_subject = _local_subject(submission)
    updates = []
    if conversation.type != Conversation.Type.NOTICE:
        conversation.type = Conversation.Type.NOTICE
        updates.append('type')
    if conversation.subject != desired_subject:
        conversation.subject = desired_subject
        updates.append('subject')
    if updates:
        conversation.save(update_fields=updates)

    _sync_workspace_participants_for_conversation(conversation, submission, extra_agent=agent)
    return conversation


@transaction.atomic
def sync_workspace_participants(submission):
    if not submission:
        raise ValueError('submission is required')
    hq = get_or_create_hq_workspace(submission)
    local = get_or_create_local_workspace(submission)
    return {
        'hq_workspace_id': hq.id,
        'local_workspace_id': local.id,
    }


def can_user_access_workspace_conversation(user, conversation):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if not conversation:
        return False

    is_participant = ConversationParticipant.objects.filter(conversation=conversation, user=user).exists()
    if not is_participant:
        return False

    workspace_type = getattr(conversation, 'workspace_type', Conversation.WorkspaceType.OTHER)
    customer_role = getattr(getattr(user, 'Role', None), 'CUSTOMER', 'CUSTOMER')
    if workspace_type == Conversation.WorkspaceType.HQ_BACKOFFICE:
        return bool(
            getattr(user, 'can_participate_in_hq_workspace', lambda: False)()
            or getattr(user, 'role', None) == customer_role
        )
    if workspace_type == Conversation.WorkspaceType.LOCAL_EXECUTION:
        return bool(getattr(user, 'can_participate_in_local_workspace', lambda: False)())
    if workspace_type == Conversation.WorkspaceType.APPOINTMENT:
        return True
    return True
