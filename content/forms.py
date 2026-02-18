from django import forms
from .models import Content


class ContentAdminForm(forms.ModelForm):
    """Admin용: allowed_roles를 체크박스로"""

    allowed_roles = forms.MultipleChoiceField(
        choices=Content.ROLE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    class Meta:
        model = Content
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['allowed_roles'] = self.instance.allowed_roles or []

    def clean_allowed_roles(self):
        data = self.cleaned_data.get('allowed_roles', [])
        return list(data) if data else []
