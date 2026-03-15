# 가족 중 Main Visa 소지자 이름(first name, last name) 문항 추가 — 신청자 정보 카드

from django.db import migrations


def add_main_visa_holder_questions(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='신청자 정보').first()
    if not section:
        return

    questions_data = [
        {
            'key': 'main_visa_holder_first_name',
            'label': '가족 중 Main Visa 소지자 이름 (First name)',
            'field_type': 'text',
            'order_in_section': 9,
            'required': False,
            'placeholder': '예: John',
            'quote_relevant': False,
            'quote_mapping_key': '',
            'quote_value_type': '',
        },
        {
            'key': 'main_visa_holder_last_name',
            'label': '가족 중 Main Visa 소지자 성 (Last name)',
            'field_type': 'text',
            'order_in_section': 10,
            'required': False,
            'placeholder': '예: Smith',
            'quote_relevant': False,
            'quote_mapping_key': '',
            'quote_value_type': '',
        },
    ]

    for q in questions_data:
        SurveyQuestion.objects.get_or_create(
            key=q['key'],
            defaults={
                'section': section,
                'order_in_section': q['order_in_section'],
                'order': q['order_in_section'],
                'step': section.display_order,
                'label': q['label'],
                'field_type': q['field_type'],
                'required': q.get('required', False),
                'choices': q.get('choices', []),
                'placeholder': q.get('placeholder', ''),
                'help_text': q.get('help_text', ''),
                'quote_relevant': q.get('quote_relevant', False),
                'quote_mapping_key': q.get('quote_mapping_key', ''),
                'quote_value_type': q.get('quote_value_type', ''),
                'is_active': True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0007_seed_default_survey_content'),
    ]

    operations = [
        migrations.RunPython(add_main_visa_holder_questions, noop),
    ]
