from django.contrib import admin
from django.contrib.admin import widgets
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models import Avg, Count, Q
from django.utils.html import format_html
from translations.utils import DisplayKey
from billing.utils import get_user_tier, get_user_grade_display
from billing.models import Plan
from .models import User, AgentRating, AgentForRating


def _tier_label(tier):
    val = getattr(tier, 'value', tier) if hasattr(tier, 'value') else tier
    return dict(Plan.Tier.choices).get(val, '베이직')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'tier_display', 'accept_rate_display', 'agent_rating_display', 'status', 'is_active')
    list_filter = ('role', 'status', 'is_active')
    search_fields = ('username', 'email')
    ordering = ('-date_joined',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # raw_id/autocomplete popup에서 role 필터 (AgentRating 등에서 사용)
        role_filter = request.GET.get('role__exact')
        if role_filter:
            qs = qs.filter(role=role_filter)
        return qs

    def tier_display(self, obj):
        out = get_user_grade_display(obj)
        return str(out) if out is not None else '-'
    tier_display.short_description = '등급(요금제)'

    def accept_rate_display(self, obj):
        if not obj or obj.role != User.Role.AGENT:
            return '-'
        if obj.accept_rate is not None:
            v = float(obj.accept_rate)
            pct = v * 100 if v <= 1 else v
            return f'{pct:.0f}%'
        from settlement.models import AgentAppointmentRequest
        stats = AgentAppointmentRequest.objects.filter(agent=obj).aggregate(
            total=Count('id'),
            confirmed=Count('id', filter=Q(status='CONFIRMED')),
            cancelled=Count('id', filter=Q(status='CANCELLED')),
        )
        total = stats['total'] or 0
        cancelled = stats['cancelled'] or 0
        total_effective = total - cancelled
        confirmed = stats['confirmed'] or 0
        if total_effective:
            return f'{(confirmed / total_effective) * 100:.0f}%'
        return '-'
    accept_rate_display.short_description = 'Accept rate'

    def agent_rating_display(self, obj):
        if not obj or obj.role != User.Role.AGENT:
            return '-'
        s = obj.get_agent_rating_summary()
        if s and (s.get('count') or 0) > 0:
            avg = s.get('avg') or 0
            count = s.get('count') or 0
            return f'{round(avg, 1):.1f}★ ({count}건)'
        return '-'
    agent_rating_display.short_description = '에이전트 별점'

    def get_fieldsets(self, request, obj=None):
        base = list(BaseUserAdmin.fieldsets) + [
            (None, {'fields': ('role', 'status', 'preferred_language')}),
            ('에이전트 정보', {
                'fields': ('profile_image', 'accept_rate', 'agent_services', 'agent_states', 'agent_cities', 'agent_cities_by_state'),
                'classes': ('collapse',),
            }),
        ]
        if obj and obj.role == User.Role.AGENT:
            base.append(('서비스별 수락 히스토리', {
                'fields': ('agent_accept_history_display',),
                'description': '이 에이전트의 서비스별 약속 요청·수락 통계입니다.',
            }))
        return base

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if obj and obj.role == User.Role.AGENT:
            ro.append('agent_accept_history_display')
        return ro

    def agent_accept_history_display(self, obj):
        if not obj or obj.role != User.Role.AGENT:
            return '-'
        from settlement.models import AgentAppointmentRequest
        from settlement.constants import get_service_label
        rows = (
            AgentAppointmentRequest.objects.filter(agent=obj)
            .values('service_code')
            .annotate(
                total=Count('id'),
                confirmed=Count('id', filter=Q(status='CONFIRMED')),
                pending=Count('id', filter=Q(status='PENDING')),
                cancelled=Count('id', filter=Q(status='CANCELLED')),
            )
            .order_by('-total')
        )
        if not rows:
            return format_html('<p class="help">아직 약속 신청 내역이 없습니다.</p>')
        lines = [
            '<table style="border-collapse:collapse; width:100%; max-width:520px;">',
            '<thead><tr style="border-bottom:1px solid #ddd;">'
            '<th style="text-align:left; padding:6px 8px;">서비스</th>'
            '<th style="text-align:right; padding:6px 8px;">전체</th>'
            '<th style="text-align:right; padding:6px 8px;">확정</th>'
            '<th style="text-align:right; padding:6px 8px;">대기</th>'
            '<th style="text-align:right; padding:6px 8px;">취소</th>'
            '<th style="text-align:right; padding:6px 8px;">수락률</th></tr></thead><tbody>',
        ]
        for r in rows:
            total = r['total'] or 0
            cancelled = r['cancelled'] or 0
            total_effective = total - cancelled
            confirmed = r['confirmed'] or 0
            rate = (confirmed / total_effective * 100) if total_effective else 0
            name = get_service_label(r['service_code'])
            lines.append(
                '<tr style="border-bottom:1px solid #eee;">'
                f'<td style="padding:6px 8px;">{name}</td>'
                f'<td style="text-align:right; padding:6px 8px;">{total}</td>'
                f'<td style="text-align:right; padding:6px 8px;">{confirmed}</td>'
                f'<td style="text-align:right; padding:6px 8px;">{r["pending"] or 0}</td>'
                f'<td style="text-align:right; padding:6px 8px;">{r["cancelled"] or 0}</td>'
                f'<td style="text-align:right; padding:6px 8px;">{rate:.0f}%</td></tr>'
            )
        lines.append('</tbody></table>')
        return format_html(''.join(lines))
    agent_accept_history_display.short_description = '서비스별 수락 히스토리'

    fieldsets = BaseUserAdmin.fieldsets + (
        (None, {'fields': ('role', 'status')}),
        ('에이전트 정보', {'fields': ('profile_image', 'accept_rate', 'agent_services', 'agent_states', 'agent_cities', 'agent_cities_by_state'), 'classes': ('collapse',)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {'fields': ('role', 'status')}),
    )


class AgentRatingInline(admin.TabularInline):
    """에이전트별 상세 페이지에서 고객 평가 목록 (조회/추가)"""
    model = AgentRating
    fk_name = 'agent'
    extra = 1
    readonly_fields = ('created_at',)
    verbose_name = DisplayKey('고객 평가')  # 고객 평가
    verbose_name_plural = DisplayKey('고객 평가 내역')  # 고객 평가 내역
    ordering = ('-created_at',)
    fields = ('rater', 'score', 'comment', 'created_at')
    raw_id_fields = ('rater',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('rater')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'rater':
            kwargs['queryset'] = User.objects.filter(role=User.Role.CUSTOMER).order_by('username')
            field = super().formfield_for_foreignkey(db_field, request, **kwargs)
            field.widget = AgentFilterRawIdWidget(
                db_field.remote_field, self.admin_site, role_filter=User.Role.CUSTOMER
            )
            return field
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class AgentFilterRawIdWidget(widgets.ForeignKeyRawIdWidget):
    """raw_id popup 시 role 파라미터로 에이전트만 필터"""

    def __init__(self, rel, admin_site, role_filter=None, **kwargs):
        self.role_filter = role_filter
        super().__init__(rel, admin_site, **kwargs)

    def url_parameters(self):
        params = super().url_parameters()
        if self.role_filter:
            params['role__exact'] = self.role_filter
        return params


@admin.register(AgentForRating)
class AgentForRatingAdmin(admin.ModelAdmin):
    """에이전트 별점: 에이전트 목록 + 클릭 시 고객 평가 세부 내역"""
    list_display = ('username', 'first_name', 'email', 'rating_avg_display', 'rating_count_display')
    list_display_links = ('username', 'first_name')
    search_fields = ('username', 'first_name', 'email')
    ordering = ('username',)
    inlines = [AgentRatingInline]
    readonly_fields = ('username', 'first_name', 'email', 'rating_summary')
    list_per_page = 50

    fieldsets = (
        (None, {'fields': ('username', 'first_name', 'email', 'rating_summary')}),
    )

    def rating_summary(self, obj):
        s = obj.get_agent_rating_summary()
        if s and s['count'] > 0:
            return f"평균 {s['avg']:.1f}★ / {s['count']}건 평가"
        return "아직 평가 없음"
    rating_summary.short_description = '별점 요약'

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=User.Role.AGENT).annotate(
            _rating_avg=Avg('ratings_received__score'),
            _rating_count=Count('ratings_received'),
        )

    def rating_avg_display(self, obj):
        avg = getattr(obj, '_rating_avg')
        if avg is not None:
            return f'{round(avg, 1):.1f}★'
        return '-'
    rating_avg_display.short_description = '평균 별점'

    def rating_count_display(self, obj):
        count = getattr(obj, '_rating_count', 0) or 0
        return f'{count}건'
    rating_count_display.short_description = '평가 수'

    def has_add_permission(self, request):
        return False  # 에이전트는 별도 가입으로만 생성

    def has_delete_permission(self, request, obj=None):
        return False  # 에이전트 삭제는 User Admin에서
