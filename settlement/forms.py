from django import forms
from translations.utils import DisplayKey
from .constants import get_all_service_codes

# US States (abbr, full name). CSV key로 첫 옵션만 조회.
US_STATES = [
    ('', DisplayKey('선택하세요')),  # 선택하세요
    ('AL', 'Alabama'), ('AK', 'Alaska'), ('AZ', 'Arizona'), ('AR', 'Arkansas'),
    ('CA', 'California'), ('CO', 'Colorado'), ('CT', 'Connecticut'),
    ('DE', 'Delaware'), ('FL', 'Florida'), ('GA', 'Georgia'), ('HI', 'Hawaii'),
    ('ID', 'Idaho'), ('IL', 'Illinois'), ('IN', 'Indiana'), ('IA', 'Iowa'),
    ('KS', 'Kansas'), ('KY', 'Kentucky'), ('LA', 'Louisiana'), ('ME', 'Maine'),
    ('MD', 'Maryland'), ('MA', 'Massachusetts'), ('MI', 'Michigan'), ('MN', 'Minnesota'),
    ('MS', 'Mississippi'), ('MO', 'Missouri'), ('MT', 'Montana'), ('NE', 'Nebraska'),
    ('NV', 'Nevada'), ('NH', 'New Hampshire'), ('NJ', 'New Jersey'), ('NM', 'New Mexico'),
    ('NY', 'New York'), ('NC', 'North Carolina'), ('ND', 'North Dakota'), ('OH', 'Ohio'),
    ('OK', 'Oklahoma'), ('OR', 'Oregon'), ('PA', 'Pennsylvania'), ('RI', 'Rhode Island'),
    ('SC', 'South Carolina'), ('SD', 'South Dakota'), ('TN', 'Tennessee'), ('TX', 'Texas'),
    ('UT', 'Utah'), ('VT', 'Vermont'), ('VA', 'Virginia'), ('WA', 'Washington'),
    ('WV', 'West Virginia'), ('WI', 'Wisconsin'), ('WY', 'Wyoming'),
    ('DC', 'Washington D.C.'),
]


class SettlementQuoteForm(forms.Form):
    """정착 서비스 견적 신청 폼"""
    services = forms.MultipleChoiceField(
        choices=(),  # 뷰에서 채움
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'service-checkbox'}),
        label=DisplayKey('서비스 선택'),  # 서비스 선택
    )
    state = forms.ChoiceField(choices=US_STATES, required=False, label=DisplayKey('이주할 State'),  # 이주할 State
        widget=forms.Select(attrs={'class': 'form-input'}))
    city = forms.CharField(max_length=100, required=False, label=DisplayKey('도시'),  # 도시
        widget=forms.TextInput(attrs={'placeholder': DisplayKey('예: Los Angeles'), 'class': 'form-input'}))
    entry_date = forms.DateField(required=False, label=DisplayKey('입국/이주 예정일'),  # 입국/이주 예정일
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}))
    name = forms.CharField(max_length=100, required=False, label=DisplayKey('이름'), widget=forms.HiddenInput())  # 이름
    email = forms.EmailField(required=False, label=DisplayKey('이메일'), widget=forms.HiddenInput())  # 이메일
    memo = forms.CharField(required=False, widget=forms.Textarea(attrs={
        'placeholder': DisplayKey('예상 일정, 지역, 특별 요청사항 등을 적어주세요.'),
        'rows': 4,
        'class': 'form-input',
    }), label=DisplayKey('추가 문의사항'))  # 추가 문의사항

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import SettlementService
        qs = SettlementService.objects.filter(is_active=True).order_by('category', 'name')
        self.fields['services'].choices = [(s.code or str(s.id), s.name) for s in qs]

    def clean_services(self):
        val = self.cleaned_data.get('services') or []
        valid = set(get_all_service_codes())
        return [s for s in val if s in valid]
