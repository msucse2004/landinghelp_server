# 공항 픽업 선택 시: 공항 이름, 날짜, 항공편, 도착 시간 문항 추가

from django.db import migrations


def add_airport_pickup_questions(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='희망 서비스').first()
    if not section:
        return

    questions_data = [
        {
            'key': 'airport_name',
            'label': '공항 이름',
            'field_type': 'text',
            'order_in_section': 3,
            'required': False,
            'placeholder': '예: LAX, JFK, SFO',
            'quote_relevant': True,
            'quote_mapping_key': 'airport_name',
            'quote_value_type': 'text',
        },
        {
            'key': 'airport_pickup_date',
            'label': '픽업 희망 날짜',
            'field_type': 'date',
            'order_in_section': 4,
            'required': False,
            'placeholder': '',
            'quote_relevant': True,
            'quote_mapping_key': 'airport_pickup_date',
            'quote_value_type': 'date',
        },
        {
            'key': 'flight_number',
            'label': '항공편',
            'field_type': 'text',
            'order_in_section': 5,
            'required': False,
            'placeholder': '예: KE017, OZ201',
            'quote_relevant': True,
            'quote_mapping_key': 'flight_number',
            'quote_value_type': 'text',
        },
        {
            'key': 'airport_arrival_time',
            'label': '도착 시간',
            'field_type': 'text',
            'order_in_section': 6,
            'required': False,
            'placeholder': '예: 14:30 (현지 시간)',
            'quote_relevant': True,
            'quote_mapping_key': 'airport_arrival_time',
            'quote_value_type': 'text',
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
        ('survey', '0010_add_other_request_content_section'),
    ]

    operations = [
        migrations.RunPython(add_airport_pickup_questions, noop),
    ]
