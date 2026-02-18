from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class FindUsernameForm(forms.Form):
    """아이디 찾기: 이메일 입력"""
    email = forms.EmailField(
        label='가입 시 사용한 이메일',
        required=True,
    )


class AdminPasswordResetForm(forms.Form):
    """Admin용 비밀번호 리셋 폼"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        label='새 비밀번호',
        min_length=1,
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        label='새 비밀번호 확인',
    )

    def clean(self):
        data = super().clean()
        p1 = data.get('new_password')
        p2 = data.get('new_password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('비밀번호가 일치하지 않습니다.')
        return data


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    role = forms.ChoiceField(
        choices=[
            ('CUSTOMER', '고객 (Customer)'),
            ('AGENT', '에이전트 (Agent)'),
        ],
        required=True,
        label='계정 유형',
    )
    birth_date = forms.DateField(
        required=True,
        label='생년월일',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    gender = forms.ChoiceField(
        choices=[
            ('', '선택하세요'),
            ('M', '남성'),
            ('F', '여성'),
            ('O', '기타'),
        ],
        required=False,
        label='성별',
    )

    class Meta:
        model = User
        fields = ('first_name', 'birth_date', 'gender', 'username', 'email', 'password1', 'password2', 'role')
