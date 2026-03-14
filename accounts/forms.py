from django import forms
from django.contrib.auth.forms import UserCreationForm
from translations.utils import DisplayKey
from .models import User, format_phone_number

# 사이트/선호 언어 드롭다운용 (User.PREFERRED_LANGUAGE_CHOICES와 동일 포맷). CSV key로 조회.
LANGUAGE_CHOICES = [
    ('ko', DisplayKey('KR 한국어')),
    ('en', DisplayKey('EN English')),
    ('es', DisplayKey('ES Español')),
    ('zh-hans', DisplayKey('ZH 中文(简体)')),
    ('zh-hant', DisplayKey('ZH 中文(繁體)')),
    ('vi', DisplayKey('VI Tiếng Việt')),
]


class FindUsernameForm(forms.Form):
    """아이디 찾기: 이메일 입력"""
    email = forms.EmailField(
        label=DisplayKey('가입 시 사용한 이메일'),  # 가입 시 사용한 이메일
        required=True,
    )


class AdminPasswordResetForm(forms.Form):
    """Admin용 비밀번호 리셋 폼"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        label=DisplayKey('새 비밀번호'),  # 새 비밀번호
        min_length=1,
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        label=DisplayKey('새 비밀번호 확인'),  # 새 비밀번호 확인
    )

    def clean(self):
        data = super().clean()
        p1 = data.get('new_password')
        p2 = data.get('new_password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(DisplayKey('비밀번호가 일치하지 않습니다.'))  # 비밀번호가 일치하지 않습니다.
        return data


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(
        choices=[
            ('CUSTOMER', DisplayKey('고객 (Customer)')),
            ('AGENT', DisplayKey('에이전트 (Agent)')),
        ],
        required=True,
        label=DisplayKey('계정 유형'),  # 계정 유형
    )
    birth_date = forms.DateField(
        required=True,
        label=DisplayKey('생년월일'),  # 생년월일
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    phone = forms.CharField(
        required=False,
        label=DisplayKey('휴대폰 번호'),  # 휴대폰 번호
        max_length=30,
    )
    gender = forms.ChoiceField(
        choices=[
            ('', DisplayKey('선택하세요')),
            ('M', DisplayKey('남성')),
            ('F', DisplayKey('여성')),
            ('O', DisplayKey('기타')),
        ],
        required=False,
        label=DisplayKey('성별'),  # 성별
    )
    preferred_language = forms.ChoiceField(
        choices=LANGUAGE_CHOICES,
        required=True,
        label=DisplayKey('선호 언어'),  # 선호 언어
        initial='ko',
    )

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '')
        return format_phone_number(phone.strip()) if phone else ''

    class Meta:
        model = User
        fields = ('role', 'first_name', 'birth_date', 'phone', 'gender', 'preferred_language', 'username', 'email', 'password1', 'password2')
