import json
from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import SurveySection, SurveyQuestion, SurveySubmission, SurveySubmissionEvent, SurveySubmissionSectionRequest


def _badge(yes, label_yes='예', label_no='아니오', green=True):
    if yes:
        color = '#16a34a' if green else '#2563eb'
        return format_html('<span style="color:{}; font-weight:600;">● {}</span>', color, label_yes)
    return format_html('<span style="color:#94a3b8;">○ {}</span>', label_no)


class SurveyQuestionInline(admin.TabularInline):
    model = SurveyQuestion
    extra = 1
    ordering = ('order_in_section', 'order')
    fields = (
        'order_in_section',
        'key',
        'label',
        'field_type',
        'required',
        'quote_relevant',
        'quote_mapping_key',
        'quote_value_type',
        'placeholder',
        'help_text',
        'choices',
        'is_active',
    )
    verbose_name = '문항'
    verbose_name_plural = '이 설문(카드)에 속한 문항 — 아래에서 추가·순서 조정'

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('order_in_section', 'order')


@admin.register(SurveySection)
class SurveySectionAdmin(admin.ModelAdmin):
    list_display = (
        'display_order',
        'title_short',
        'customer_visible_badge',
        'is_active',
        'is_internal',
        'question_count',
        'updated_at',
    )
    list_display_links = ('title_short',)
    list_editable = ('display_order', 'is_active', 'is_internal')
    list_filter = ('is_active', 'is_internal')
    search_fields = ('title', 'description')
    ordering = ('display_order', 'id')
    inlines = (SurveyQuestionInline,)
    fieldsets = (
        ('설문(카드) 정보', {
            'fields': ('title', 'description', 'display_order', 'is_active', 'is_internal'),
            'description': mark_safe(
                '<p style="margin-bottom:0.5rem;">설문 하나 = 카드 하나. <strong>제목</strong>·<strong>설명</strong>을 넣고, 아래에서 문항을 추가하세요.</p>'
                '<p style="color:#64748b; font-size:0.9rem;">표시 순서가 작을수록 먼저 나옵니다. Admin 전용 체크 시 고객에게 안 보입니다.</p>'
            ),
        }),
        ('조건부 노출 (선택)', {
            'fields': ('visibility_condition',),
            'description': '예: {"depends_on": "question_key", "value": "expected"}',
        }),
    )

    def title_short(self, obj):
        t = (obj.title or '')[:50]
        return t + ('…' if len(obj.title or '') > 50 else '')
    title_short.short_description = '제목'

    def customer_visible_badge(self, obj):
        if obj.is_internal:
            return format_html('<span style="color:#94a3b8;">Admin 전용</span>')
        return format_html('<span style="color:#16a34a; font-weight:600;">● 고객 노출</span>')
    customer_visible_badge.short_description = '고객 노출'

    def question_count(self, obj):
        return obj.questions.count()
    question_count.short_description = '문항 수'


# 설문 문항은 상단 "설문" 메뉴에서 카드별로 인라인 편집만 가능 (별도 메뉴 없음)


class SurveySubmissionEventInline(admin.TabularInline):
    model = SurveySubmissionEvent
    extra = 0
    readonly_fields = ('event_type', 'created_at', 'created_by', 'meta')
    can_delete = False
    ordering = ('-created_at',)
    verbose_name = '이벤트'

    def has_add_permission(self, request, obj=None):
        return False


class SurveySubmissionSectionRequestInline(admin.TabularInline):
    model = SurveySubmissionSectionRequest
    extra = 0
    readonly_fields = ('section', 'message', 'requested_at', 'requested_by', 'resolved_at')
    ordering = ('section__display_order', 'id')
    verbose_name = '카드별 수정 요청'

    def has_add_permission(self, request, obj=None):
        return False


class SurveySubmissionAdminForm(forms.ModelForm):
    """계정당 설문 1건만 허용: 동일 user 중복 시 user 필드에 오류 표시."""

    class Meta:
        model = SurveySubmission
        fields = '__all__'

    def clean_user(self):
        user = self.cleaned_data.get('user')
        if not user:
            return user
        pk = self.instance.pk if self.instance else None
        if SurveySubmission.objects.filter(user=user).exclude(pk=pk).exists():
            raise ValidationError('이 사용자에게 이미 설문 제출이 등록되어 있습니다. 계정당 1건만 허용됩니다.')
        return user


@admin.register(SurveySubmission)
class SurveySubmissionAdmin(admin.ModelAdmin):
    form = SurveySubmissionAdminForm
    list_display = (
        'email',
        'status',
        'current_step',
        'updated_at',
        'revision_requested_at',
        'submitted_at',
        'user',
        'preferred_support_mode_short',
    )
    list_filter = ('status', 'updated_at')
    search_fields = ('email', 'user__email', 'user__username')
    readonly_fields = ('updated_at', 'submitted_at', 'last_reminded_at', 'answers_display', 'quote_input_preview')
    inlines = (SurveySubmissionEventInline, SurveySubmissionSectionRequestInline,)
    actions = ('request_revision_from_customer', 'generate_quote_draft',)

    fieldsets = (
        (None, {
            'fields': ('user', 'email', 'status', 'current_step'),
        }),
        ('수정 요청 (고객 재제출 유도)', {
            'fields': ('revision_requested_at', 'revision_requested_message'),
            'description': '고객 수정 요청 시 메시지를 입력한 뒤 아래 "Request revision from customer" 액션을 실행하세요.',
        }),
        ('저장 시각', {
            'fields': ('updated_at', 'last_reminded_at', 'submitted_at'),
        }),
        ('답변 (보기)', {
            'fields': ('answers_display', 'quote_input_preview'),
            'description': '제출 내용을 보기 좋게 표시. 견적 입력 미리보기는 quote_relevant 문항 기준 정규화 결과입니다.',
        }),
        ('답변 (원본)', {
            'fields': ('answers',),
            'description': 'DRAFT/REVISION_REQUESTED 시 answers 수정 가능.',
        }),
        ('서비스 요청', {
            'fields': ('preferred_support_mode', 'requested_required_services', 'requested_optional_services'),
        }),
    )

    @admin.action(description='고객에게 수정 요청')
    def request_revision_from_customer(self, request, queryset):
        from .models import SurveySubmissionEvent
        updated = 0
        for obj in queryset:
            if obj.status != SurveySubmission.Status.SUBMITTED:
                continue
            obj.status = SurveySubmission.Status.REVISION_REQUESTED
            obj.revision_requested_at = timezone.now()
            obj.save(update_fields=['status', 'revision_requested_at'])
            SurveySubmissionEvent.objects.create(
                submission=obj,
                event_type=SurveySubmissionEvent.EventType.REVISION_REQUESTED,
                created_by=request.user,
                meta={'message': (obj.revision_requested_message or '')[:500]},
            )
            updated += 1
        self.message_user(request, f'{updated}건에 수정 요청 상태를 적용했습니다. 고객이 설문에서 다시 편집·제출할 수 있습니다.')

    @admin.action(description='견적 초안 자동 생성')
    def generate_quote_draft(self, request, queryset):
        from settlement.quote_draft import generate_quote_draft_from_submission
        created = updated = 0
        for obj in queryset:
            try:
                q, c = generate_quote_draft_from_submission(obj, actor=request.user)
                if q:
                    if c:
                        created += 1
                    else:
                        updated += 1
            except Exception as e:
                self.message_user(request, f'제출 #{obj.id} 오류: {e}', level=40)
        self.message_user(request, f'견적 초안 생성 {created}건, 갱신 {updated}건.')

    def preferred_support_mode_short(self, obj):
        s = (obj.preferred_support_mode or '')[:30]
        return s + ('…' if len(obj.preferred_support_mode or '') > 30 else '')
    preferred_support_mode_short.short_description = '지원 방식'

    def quote_input_preview(self, obj):
        """견적 자동화용 정규화 입력 미리보기."""
        if not obj:
            return mark_safe('<p class="text-muted">—</p>')
        try:
            from .quote_input import get_quote_input_data
            data = get_quote_input_data(obj)
            lines = ['<table style="border-collapse:collapse; max-width:480px;"><tbody>']
            for k, v in data.items():
                if v is None or v == [] or v == '':
                    disp = '<em>비어 있음</em>'
                elif isinstance(v, list):
                    disp = ', '.join(str(x) for x in v) if v else '<em>없음</em>'
                else:
                    disp = str(v)
                lines.append(f'<tr><td style="padding:4px 8px; font-weight:500;">{k}</td><td style="padding:4px 8px;">{disp}</td></tr>')
            lines.append('</tbody></table>')
            return mark_safe(''.join(lines))
        except Exception as e:
            return mark_safe(f'<p class="text-muted">오류: {e}</p>')
    quote_input_preview.short_description = '견적 입력 미리보기'

    def answers_display(self, obj):
        """답변을 보기 좋게 테이블로 렌더링."""
        if not obj or not obj.answers:
            return mark_safe('<p class="text-muted">답변 없음</p>')
        try:
            rows = []
            for key, value in (obj.answers or {}).items():
                if value is None or value == '':
                    disp = '<em>비어 있음</em>'
                elif isinstance(value, list):
                    disp = ', '.join(str(v) for v in value) if value else '<em>없음</em>'
                elif isinstance(value, dict):
                    disp = json.dumps(value, ensure_ascii=False, indent=2)
                else:
                    disp = str(value)
                rows.append(f'<tr><td style="vertical-align:top; padding:6px 8px; font-weight:500;">{key}</td><td style="padding:6px 8px;">{disp}</td></tr>')
            table = '<table style="border-collapse:collapse; width:100%; max-width:640px;"><tbody>' + ''.join(rows) + '</tbody></table>'
            return mark_safe(table)
        except Exception:
            return mark_safe('<pre>{}</pre>'.format(json.dumps(obj.answers, ensure_ascii=False, indent=2)))
    answers_display.short_description = '답변 요약'
