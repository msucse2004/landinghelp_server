# ai_agent: Admin-managed knowledge and interaction logging
from django.db import models
from django.conf import settings


class AssistantKnowledge(models.Model):
    """
    Admin-managed knowledge for the AI assistant: FAQs, service instructions, internal notes.
    Used by context_builder to inject into the assistant context.
    """

    class Category(models.TextChoices):
        FAQ = 'FAQ', 'FAQ'
        SERVICE_INSTRUCTION = 'SERVICE_INSTRUCTION', '서비스 안내'
        INTERNAL_NOTE = 'INTERNAL_NOTE', '내부 메모'

    title = models.CharField(max_length=200, verbose_name='제목')
    content = models.TextField(verbose_name='내용', help_text='어시스턴트가 참고할 텍스트.')
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        default=Category.FAQ,
        db_index=True,
        verbose_name='분류',
    )
    service_code = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        verbose_name='서비스 코드',
        help_text='특정 서비스에만 적용할 때 코드 입력. 비우면 전체.',
    )
    is_active = models.BooleanField(default=True, verbose_name='활성')
    display_order = models.PositiveIntegerField(default=0, verbose_name='표시 순서')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'id']
        verbose_name = '어시스턴트 지식'
        verbose_name_plural = '어시스턴트 지식'

    def __str__(self):
        return f'{self.title} ({self.get_category_display()})'


class AssistantInteractionLog(models.Model):
    """
    Log of assistant interactions for guardrails, debugging, and future improvement.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assistant_interaction_logs',
        verbose_name='사용자',
    )
    conversation = models.ForeignKey(
        'messaging.Conversation',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='assistant_logs',
        verbose_name='대화',
    )
    message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assistant_logs',
        verbose_name='응답 메시지',
    )
    role = models.CharField(max_length=20)  # 'user' | 'assistant'
    input_text = models.TextField(blank=True, verbose_name='입력(사용자 메시지 또는 컨텍스트 요약)')
    output_text = models.TextField(blank=True, verbose_name='출력(어시스턴트 응답)')
    model_used = models.CharField(max_length=100, blank=True, verbose_name='사용 모델')
    uncertainty_flagged = models.BooleanField(default=False, verbose_name='불확실성 플래그')
    meta = models.JSONField(default=dict, blank=True, verbose_name='메타')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '어시스턴트 상호작용 로그'
        verbose_name_plural = '어시스턴트 상호작용 로그'

    def __str__(self):
        return f'{self.user_id} / {self.role} @ {self.created_at}'
