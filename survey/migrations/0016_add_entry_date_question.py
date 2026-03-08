# 고객 설문에 예상 입국일 문항 추가 (입국 인원 카드)

from django.db import migrations


def add_entry_date_question(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='입국 인원').first()
    if not section:
        return

    SurveyQuestion.objects.get_or_create(
        key='entry_date',
        defaults={
            'section': section,
            'order_in_section': 3,
            'order': 3,
            'step': section.display_order,
            'label': '예상 입국일',
            'field_type': 'date',
            'required': False,
            'choices': [],
            'placeholder': '',
            'help_text': '미국 입국 예정일이 있으면 선택해 주세요.',
            'quote_relevant': True,
            'quote_mapping_key': 'entry_date',
            'quote_value_type': 'date',
            'is_active': True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0015_one_submission_per_user'),
    ]

    operations = [
        migrations.RunPython(add_entry_date_question, noop),
    ]
