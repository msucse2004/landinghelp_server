# 희망 서비스 카드 추가: 카테고리별 서비스 선택 + 주택 선택 시 희망 거주 형태

from django.db import migrations


def add_hoped_services_section(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section, _ = SurveySection.objects.get_or_create(
        title='희망 서비스',
        defaults={
            'description': '필요한 서비스를 카테고리별로 선택해 주세요. (중복 선택 가능)',
            'display_order': 5,
            'is_active': True,
            'is_internal': False,
        },
    )

    # 희망 서비스 (카테고리별 체크박스 - 템플릿에서 requested_required_services로 렌더)
    SurveyQuestion.objects.get_or_create(
        key='requested_required_services',
        defaults={
            'section': section,
            'order_in_section': 1,
            'order': 1,
            'step': 5,
            'label': '희망 서비스',
            'field_type': 'checkbox',
            'required': False,
            'choices': [],
            'placeholder': '',
            'help_text': '카테고리별로 원하는 서비스를 체크하세요.',
            'quote_relevant': True,
            'quote_mapping_key': 'service_codes',
            'quote_value_type': 'service_codes',
            'is_active': True,
        },
    )

    # 희망 거주 형태 (주거/임대 서비스 선택 시에만 노출)
    SurveyQuestion.objects.get_or_create(
        key='desired_housing_type',
        defaults={
            'section': section,
            'order_in_section': 2,
            'order': 2,
            'step': 5,
            'label': '희망 거주 형태',
            'field_type': 'select',
            'required': False,
            'choices': [
                {'value': 'condo_apt', 'label': '콘도, 아파트'},
                {'value': 'townhouse', 'label': '타운 하우스'},
                {'value': 'single_house', 'label': '싱글 하우스'},
                {'value': 'any', 'label': '아무 형태나 상관 없음'},
            ],
            'placeholder': '',
            'help_text': '주택 관련 서비스를 선택한 경우 희망하시는 거주 형태를 골라 주세요.',
            'quote_relevant': True,
            'quote_mapping_key': 'desired_housing_type',
            'quote_value_type': 'options',
            'is_active': True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0008_add_main_visa_holder_name_questions'),
    ]

    operations = [
        migrations.RunPython(add_hoped_services_section, noop),
    ]
