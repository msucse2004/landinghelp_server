import logging

from django.contrib import admin
from django.db import OperationalError, ProgrammingError
from django.db.models import Count, IntegerField, Max, OuterRef, Subquery
from django.utils import timezone
from .models import (
    Conversation, ConversationParticipant, Message, MessageRead,
    CustomerRequestIntentAnalysis, CustomerActionProposal, CustomerActionFeedbackLog,
    CustomerRequestFeedbackEvent, CustomerRequestLearningSummary,
    CustomerRequestManualLabelRevision, PageKeyFeedbackScore,
)


logger = logging.getLogger(__name__)


class ConversationParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    raw_id_fields = ('user',)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    raw_id_fields = ('sender',)
    readonly_fields = ('created_at',)


# 대화·메시지·메시지 읽음을 관리 메뉴에서 하나로 합침: '대화'만 등록하고,
# 참여자·메시지는 대화 상세 인라인에서만 관리. Message/MessageRead는 별도 메뉴 제거.
@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'subject', 'appointment', 'created_at', 'updated_at')
    list_filter = ('type',)
    search_fields = ('subject',)
    raw_id_fields = ('appointment',)
    inlines = (ConversationParticipantInline, MessageInline)
    readonly_fields = ('created_at', 'updated_at')


# 메뉴를 하나로 하기 위해 Message, MessageRead는 등록하지 않음 (대화 인라인으로만 편집)
# 필요 시 아래처럼 다시 등록하면 '메시지'/'메시지 읽음' 메뉴가 복구됨.
# @admin.register(Message)
# class MessageAdmin(admin.ModelAdmin): ...
# @admin.register(MessageRead)
# class MessageReadAdmin(admin.ModelAdmin): ...


# ---------------------------------------------------------------------------
# 고객 요청 분류·제안·피드백 Admin
# ---------------------------------------------------------------------------

class CustomerActionProposalInline(admin.TabularInline):
    model = CustomerActionProposal
    extra = 0
    fields = (
        'proposal_type', 'action_code', 'status',
        'created_at', 'confirmed_at', 'executed_at',
    )
    readonly_fields = ('created_at', 'confirmed_at', 'executed_at')
    show_change_link = True


class CustomerActionFeedbackLogInline(admin.TabularInline):
    model = CustomerActionFeedbackLog
    extra = 0
    fields = ('event_type', 'actor', 'event_payload', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(CustomerRequestIntentAnalysis)
class CustomerRequestIntentAnalysisAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'original_text', 'duplicate_count_display', 'predicted_intent', 'predicted_action',
        'execution_mode', 'source',
    )
    list_filter = ('predicted_intent', 'execution_mode', 'source')
    search_fields = ('original_text', 'customer__username', 'customer__email')
    raw_id_fields = ('customer', 'conversation', 'message')
    list_display_links = ('id',)
    list_editable = ('original_text', 'predicted_intent', 'predicted_action', 'execution_mode')
    readonly_fields = (
        'customer', 'conversation', 'message',
        'normalized_text',
        'confidence', 'source',
        'raw_model_output', 'target_section_ids', 'route_candidates',
        'request_id', 'created_at',
    )
    fieldsets = (
        ('수정 가능', {
            'fields': ('original_text', 'predicted_intent', 'predicted_action', 'execution_mode'),
        }),
        ('상세 정보 (읽기 전용)', {
            'fields': (
                'customer', 'conversation', 'message',
                'confidence', 'source', 'normalized_text',
                'raw_model_output', 'target_section_ids', 'route_candidates',
                'request_id', 'created_at',
            ),
        }),
    )
    inlines = (CustomerActionProposalInline,)

    class Media:
        js = ('messaging/admin/customer_request_intent_analysis_columns.js',)

    @admin.display(description='중복 건수')
    def duplicate_count_display(self, obj):
        total = int(getattr(obj, 'duplicate_count', 1) or 1)
        return max(total - 1, 0)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        dup_count_subquery = (
            qs.filter(original_text=OuterRef('original_text'))
            .values('original_text')
            .annotate(c=Count('id'))
            .values('c')[:1]
        )
        latest_ids = (
            qs.values('original_text')
            .annotate(latest_id=Max('id'))
            .values_list('latest_id', flat=True)
        )
        return (
            qs.filter(id__in=latest_ids)
            .annotate(duplicate_count=Subquery(dup_count_subquery, output_field=IntegerField()))
            .order_by('-id')
        )

    def _sync_learning_summary_from_analysis(self, request, obj, form):
        changed = set(form.changed_data or [])
        sync_fields = {'original_text', 'predicted_intent', 'predicted_action', 'execution_mode'}
        if not changed.intersection(sync_fields):
            return

        rid = (getattr(obj, 'request_id', '') or '').strip()
        if not rid:
            return

        try:
            summary_obj, _ = CustomerRequestLearningSummary.objects.get_or_create(request_id=rid)
            before_intent = (summary_obj.manual_confirmed_intent or '').strip()
            before_page = (summary_obj.manual_confirmed_page_key or '').strip()
            before_notes = (summary_obj.manual_label_notes or '').strip()

            summary_payload = summary_obj.summary if isinstance(summary_obj.summary, dict) else {}
            summary_payload = dict(summary_payload)
            summary_payload['user_message'] = (obj.original_text or '').strip()
            summary_payload['predicted_intent'] = (obj.predicted_intent or '').strip()
            summary_payload['predicted_action'] = (obj.predicted_action or '').strip()
            summary_payload['execution_mode'] = (obj.execution_mode or '').strip()

            update_fields = {'summary', 'updated_at'}
            summary_obj.summary = summary_payload

            new_intent = (obj.predicted_intent or '').strip()
            changed_by = request.user if getattr(request.user, 'is_authenticated', False) else None
            if new_intent and before_intent != new_intent:
                summary_obj.manual_confirmed_intent = new_intent
                summary_obj.manual_labeled_by = changed_by
                summary_obj.manual_labeled_at = timezone.now()
                update_fields.update({'manual_confirmed_intent', 'manual_labeled_by', 'manual_labeled_at'})

            summary_obj.save(update_fields=list(update_fields))

            if new_intent and before_intent != new_intent:
                CustomerRequestManualLabelRevision.objects.create(
                    learning_summary=summary_obj,
                    request_id=rid,
                    before_intent=before_intent,
                    after_intent=new_intent,
                    before_page_key=before_page,
                    after_page_key=(summary_obj.manual_confirmed_page_key or '').strip(),
                    before_notes=before_notes,
                    after_notes=(summary_obj.manual_label_notes or '').strip(),
                    changed_by=changed_by,
                )
        except (ProgrammingError, OperationalError) as e:
            logger.warning(
                "skip learning summary sync for request_id=%s due to db schema mismatch: %s",
                rid,
                e,
            )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._sync_learning_summary_from_analysis(request, obj, form)


@admin.register(CustomerActionProposal)
class CustomerActionProposalAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'proposal_type', 'action_code', 'status',
        'created_at', 'confirmed_at', 'executed_at',
    )
    list_filter = ('proposal_type', 'status')
    search_fields = ('title', 'action_code')
    raw_id_fields = ('analysis', 'submission', 'quote', 'conversation', 'confirmed_by')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (CustomerActionFeedbackLogInline,)


@admin.register(CustomerActionFeedbackLog)
class CustomerActionFeedbackLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'proposal', 'event_type', 'actor', 'created_at')
    list_filter = ('event_type',)
    raw_id_fields = ('proposal', 'actor')
    readonly_fields = ('created_at',)


# ---------------------------------------------------------------------------
# 설문 수정 흐름 학습용 이벤트 로그 (추천 vs 실제 수정 페이지 추적)
# ---------------------------------------------------------------------------


@admin.register(CustomerRequestFeedbackEvent)
class CustomerRequestFeedbackEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'request_id', 'event_type', 'user', 'survey_submission', 'page_key', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('request_id', 'message_text')
    raw_id_fields = ('user', 'survey_submission')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(CustomerRequestLearningSummary)
class CustomerRequestLearningSummaryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'request_id', 'label_quality', 'label_source_display',
        'manual_confirmed_intent', 'manual_confirmed_page_key',
        'manual_labeled_by', 'manual_labeled_at', 'updated_at',
    )
    list_filter = ('label_quality', 'manual_confirmed_intent')
    search_fields = ('request_id',)
    readonly_fields = ('request_id', 'summary', 'label_quality', 'created_at', 'updated_at', 'manual_labeled_at')
    raw_id_fields = ('manual_labeled_by',)
    date_hierarchy = 'updated_at'
    actions = ('rebuild_feedback_scores_action',)

    fields = (
        'request_id',
        'summary',
        'label_quality',
        'manual_confirmed_intent',
        'manual_confirmed_page_key',
        'manual_label_notes',
        'manual_labeled_by',
        'manual_labeled_at',
        'created_at',
        'updated_at',
    )

    @admin.display(description='라벨 소스')
    def label_source_display(self, obj):
        return obj.label_source

    def save_model(self, request, obj, form, change):
        manual_fields = {'manual_confirmed_intent', 'manual_confirmed_page_key', 'manual_label_notes'}
        if change and manual_fields.intersection(set(form.changed_data or [])):
            before_obj = CustomerRequestLearningSummary.objects.filter(pk=obj.pk).first()
            changed_by = request.user if getattr(request.user, 'is_authenticated', False) else None
            obj.manual_labeled_by = changed_by
            obj.manual_labeled_at = timezone.now()
        super().save_model(request, obj, form, change)
        if change and manual_fields.intersection(set(form.changed_data or [])):
            CustomerRequestManualLabelRevision.objects.create(
                learning_summary=obj,
                request_id=obj.request_id,
                before_intent=(getattr(before_obj, 'manual_confirmed_intent', '') or '').strip() if before_obj else '',
                after_intent=(obj.manual_confirmed_intent or '').strip(),
                before_page_key=(getattr(before_obj, 'manual_confirmed_page_key', '') or '').strip() if before_obj else '',
                after_page_key=(obj.manual_confirmed_page_key or '').strip(),
                before_notes=(getattr(before_obj, 'manual_label_notes', '') or '').strip() if before_obj else '',
                after_notes=(obj.manual_label_notes or '').strip(),
                changed_by=changed_by,
            )


@admin.register(CustomerRequestManualLabelRevision)
class CustomerRequestManualLabelRevisionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'request_id', 'learning_summary', 'before_intent', 'after_intent',
        'before_page_key', 'after_page_key', 'changed_by', 'changed_at',
    )
    list_filter = ('changed_at',)
    search_fields = ('request_id', 'before_intent', 'after_intent', 'before_page_key', 'after_page_key')
    raw_id_fields = ('learning_summary', 'changed_by')
    readonly_fields = (
        'learning_summary', 'request_id', 'before_intent', 'after_intent',
        'before_page_key', 'after_page_key', 'before_notes', 'after_notes',
        'changed_by', 'changed_at',
    )

    @admin.action(description='피드백 점수 재계산 (PageKeyFeedbackScore)')
    def rebuild_feedback_scores_action(self, request, queryset):
        from .feedback_scores import rebuild_feedback_scores

        result = rebuild_feedback_scores()
        updated = int((result or {}).get('updated') or 0)
        self.message_user(request, f'피드백 점수 재계산 완료: {updated}개 page_key 업데이트')


@admin.register(PageKeyFeedbackScore)
class PageKeyFeedbackScoreAdmin(admin.ModelAdmin):
    list_display = (
        'page_key', 'score_boost', 'total_seen',
        'thumbs_up_count', 'thumbs_down_count',
        'positive_label_count', 'negative_label_count',
        'updated_at',
    )
    list_filter = ('updated_at',)
    search_fields = ('page_key',)
    readonly_fields = (
        'page_key', 'score_boost', 'total_seen',
        'thumbs_up_count', 'thumbs_down_count',
        'positive_label_count', 'negative_label_count',
        'updated_at',
    )
    ordering = ('-score_boost',)
