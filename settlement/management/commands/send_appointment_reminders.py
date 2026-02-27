# 24시간 지나도 수락하지 않은 예약에 대해 에이전트에게 독촉 메시지 발송
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model

from settlement.models import AgentAppointmentRequest
from messaging.models import Conversation, ConversationParticipant, Message


class Command(BaseCommand):
    help = '24시간이 지나도 수락하지 않은 예약에 대해 해당 에이전트에게 독촉 알림 메시지를 보냅니다. (발신: admin, 수신: 에이전트)'

    def handle(self, *args, **options):
        User = get_user_model()
        admin_user = User.objects.filter(is_staff=True).order_by('pk').first()
        if not admin_user:
            self.stdout.write(self.style.WARNING('staff 사용자가 없어 알림을 보내지 않습니다.'))
            return

        threshold = timezone.now() - timedelta(hours=24)
        pending = AgentAppointmentRequest.objects.filter(
            status='PENDING',
            reminder_sent_at__isnull=True,
            created_at__lt=threshold,
        ).select_related('agent')

        sent = 0
        for req in pending:
            agent = req.agent
            if not agent:
                continue
            subject = '약속 수락 독촉'
            body = f'예약 #{req.id}을(를) 빨리 수락해 주세요.'
            conv = Conversation.objects.create(
                type=Conversation.Type.NOTICE,
                subject=subject,
            )
            ConversationParticipant.objects.create(conversation=conv, user=admin_user)
            ConversationParticipant.objects.get_or_create(conversation=conv, user=agent)
            Message.objects.create(conversation=conv, sender=admin_user, body=body)
            req.reminder_sent_at = timezone.now()
            req.save(update_fields=['reminder_sent_at'])
            sent += 1
            self.stdout.write(f'  예약 #{req.id} → 에이전트 {agent.username}에게 독촉 메시지 발송')

        self.stdout.write(self.style.SUCCESS(f'총 {sent}건 독촉 메시지를 발송했습니다.'))
