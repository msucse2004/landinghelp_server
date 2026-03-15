# 서비스 진행 방식: 일괄 vs 개별 선택 모드 문항 추가

from django.db import migrations


def add_delivery_mode_question(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='서비스 진행 방식').first()
    if not section:
        return

    # 적용 방식 (일괄 / 서비스별)
    SurveyQuestion.objects.get_or_create(
        key='service_delivery_mode',
        defaults={
            'section': section,
            'order_in_section': 1,
            'order': 1,
            'step': section.display_order,
            'label': '적용 방식을 선택해 주세요',
            'field_type': 'radio',
            'required': False,
            'choices': [
                {'value': 'bulk', 'label': '전체에 일괄 적용 — 선택한 모든 서비스에 동일하게 적용할게요'},
                {'value': 'per_service', 'label': '서비스마다 다르게 선택 — 서비스별로 진행 방식을 골라요'},
            ],
            'placeholder': '',
            'help_text': '',
            'quote_relevant': False,
            'quote_mapping_key': '',
            'quote_value_type': '',
            'is_active': True,
        },
    )

    # 기존 일괄 선택 문항을 order_in_section 2로 변경
    SurveyQuestion.objects.filter(key='service_delivery_preference').update(order_in_section=2, order=2)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0013_reorder_service_delivery_before_other'),
    ]

    operations = [
        migrations.RunPython(add_delivery_mode_question, noop),
    ]
