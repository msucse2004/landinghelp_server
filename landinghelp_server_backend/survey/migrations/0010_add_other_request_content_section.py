# 기타 의뢰 내용 카드 추가 — 텍스트 입력

from django.db import migrations


def add_other_request_section(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section, _ = SurveySection.objects.get_or_create(
        title='기타 의뢰 내용',
        defaults={
            'description': '추가로 전달하고 싶은 내용이 있으면 자유롭게 적어 주세요.',
            'display_order': 6,
            'is_active': True,
            'is_internal': False,
        },
    )

    SurveyQuestion.objects.get_or_create(
        key='other_request_content',
        defaults={
            'section': section,
            'order_in_section': 1,
            'order': 1,
            'step': 6,
            'label': '기타 의뢰 내용',
            'field_type': 'textarea',
            'required': False,
            'choices': [],
            'placeholder': '예: 입국 일정, 특별히 도움이 필요한 부분, 선호하는 연락 방식 등',
            'help_text': '',
            'quote_relevant': True,
            'quote_mapping_key': 'special_requirements',
            'quote_value_type': 'text',
            'is_active': True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0009_hoped_services_section_and_housing_type'),
    ]

    operations = [
        migrations.RunPython(add_other_request_section, noop),
    ]
