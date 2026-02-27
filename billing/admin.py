from django import forms
from django.contrib import admin
from django.utils.html import format_html
from .models import Plan


def _get_service_choices():
    from settlement.models import SettlementService
    qs = SettlementService.objects.filter(is_active=True).order_by('category', 'name')
    return [(s.code or str(s.id), f'{s.name} ({s.code or s.id})') for s in qs]


class PlanAdminForm(forms.ModelForm):
    free_agent_service_codes = forms.MultipleChoiceField(
        choices=[],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='무료 Agent 서비스 항목',
        help_text='이 요금제에서 무료로 제공하는 정착 서비스. 예: Standard에 공항픽업 추가.',
    )

    class Meta:
        model = Plan
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['free_agent_service_codes'].choices = _get_service_choices()
        self.initial['free_agent_service_codes'] = (self.instance.free_agent_service_codes or []) if self.instance else []

    def clean_free_agent_service_codes(self):
        return list(self.cleaned_data.get('free_agent_service_codes') or [])


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    form = PlanAdminForm
    list_display = ('name', 'target_role', 'duration_display', 'free_agent_services_preview', 'is_active')
    list_filter = ('target_role', 'is_active')
    search_fields = ('name', 'code')
    ordering = ('target_role', 'name')
    fieldsets = (
        (None, {'fields': ('name', 'target_role', 'duration_months', 'is_active')}),
        ('서비스 정책 (요금제별 적용)', {
            'fields': ('can_use_llm',),
            'description': '고객이 이 요금제로 구독 시 적용되는 정책. LLM(AI) 서비스 사용 여부만 설정. 비워두면 기존 tier 값으로 동작합니다.',
        }),
        ('고객 플랜 옵션', {
            'fields': ('free_agent_service_codes',),
            'description': '이 요금제에서 무료로 제공하는 Agent 서비스 항목을 선택하세요. 예: Standard → 공항픽업.',
        }),
    )

    def duration_display(self, obj):
        n = getattr(obj, 'duration_months', 1) or 0
        return '무제한' if n == 0 else f'{n}개월'

    duration_display.short_description = '유지 기간'

    def free_agent_services_preview(self, obj):
        codes = obj.free_agent_service_codes or []
        if not codes:
            return '-'
        if len(codes) <= 3:
            return ', '.join(codes)
        return ', '.join(codes[:3]) + '…'

    free_agent_services_preview.short_description = '무료 Agent 서비스'

    change_form_template = 'admin/billing/plan/change_form.html'
