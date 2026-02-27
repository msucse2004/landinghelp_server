# messaging: 고객↔에이전트 약속 대화, 관리자 공지
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """대화/스레드. 약속 요청에 연결되거나 관리자 공지용."""

    class Type(models.TextChoices):
        APPOINTMENT = 'APPOINTMENT', '약속 대화'
        NOTICE = 'NOTICE', '공지'

    type = models.CharField(
        max_length=20,
        choices=Type.choices,
        default=Type.APPOINTMENT,
    )
    appointment = models.ForeignKey(
        'settlement.AgentAppointmentRequest',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='conversations',
        verbose_name='약속 신청',
    )
    subject = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='제목',
        help_text='공지일 때 제목',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '대화'
        verbose_name_plural = '대화'
        ordering = ['-updated_at']

    def __str__(self):
        if self.appointment_id:
            return f'약속 대화 #{self.appointment_id}'
        return self.subject or f'공지 #{self.pk}'


class ConversationParticipant(models.Model):
    """대화 참여자 (누가 이 대화를 볼 수 있는지)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='participants',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation_participations',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '대화 참여자'
        verbose_name_plural = '대화 참여자'
        unique_together = [['conversation', 'user']]
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user.username} in conv #{self.conversation_id}'


class Message(models.Model):
    """대화 안의 메시지 한 건."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='보낸 사람',
    )
    body = models.TextField(verbose_name='내용', blank=True)
    image = models.ImageField(
        upload_to='messaging/%Y/%m/',
        blank=True,
        null=True,
        verbose_name='첨부 이미지',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '메시지'
        verbose_name_plural = '메시지'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender.username}: {self.body[:30]}...'


class MessageRead(models.Model):
    """메시지 읽음 상태 (알림/미읽음 표시용)."""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='read_by',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_reads',
    )
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '메시지 읽음'
        verbose_name_plural = '메시지 읽음'
        unique_together = [['message', 'user']]
        ordering = ['read_at']

    def __str__(self):
        return f'{self.user.username} read msg #{self.message_id}'
