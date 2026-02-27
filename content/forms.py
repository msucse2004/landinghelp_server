from django import forms
from .models import Content, CorporateAdRequest


class ContentAdminForm(forms.ModelForm):
    class Meta:
        model = Content
        fields = '__all__'


class CorporateAdRequestForm(forms.ModelForm):
    class Meta:
        model = CorporateAdRequest
        fields = ('company_name', 'contact_name', 'email', 'phone', 'ad_title', 'ad_subtitle', 'link_url', 'memo')
        widgets = {
            'company_name': forms.TextInput(attrs={'placeholder': '회사 또는 업체명', 'class': 'form-input'}),
            'contact_name': forms.TextInput(attrs={'placeholder': '담당자 이름', 'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'placeholder': 'example@company.com', 'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'placeholder': '010-0000-0000', 'class': 'form-input'}),
            'ad_title': forms.TextInput(attrs={'placeholder': '광고에 표시할 제목', 'class': 'form-input'}),
            'ad_subtitle': forms.TextInput(attrs={'placeholder': '광고에 표시할 부제목 (선택)', 'class': 'form-input'}),
            'link_url': forms.URLInput(attrs={'placeholder': 'https://', 'class': 'form-input'}),
            'memo': forms.Textarea(attrs={'placeholder': '추가 요청사항', 'rows': 4, 'class': 'form-input'}),
        }
