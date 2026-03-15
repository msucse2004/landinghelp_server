from django.db import migrations
from django.db.models import F


def add_birth_date_question(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='신청자 정보').first()
    if not section:
        return

    # 기존 order_in_section >= 4 인 문항을 +1 씩 밀어 birth_date 자리 확보
    SurveyQuestion.objects.filter(
        section=section,
        order_in_section__gte=4,
    ).order_by('-order_in_section').update(
        order_in_section=F('order_in_section') + 1,
        order=F('order') + 1,
    )

    SurveyQuestion.objects.get_or_create(
        key='birth_date',
        defaults={
            'section': section,
            'order_in_section': 4,
            'order': 4,
            'step': section.display_order,
            'label': '생년월일',
            'field_type': 'date',
            'required': False,
            'choices': [],
            'placeholder': '',
            'help_text': '',
            'quote_relevant': False,
            'quote_mapping_key': '',
            'quote_value_type': '',
            'is_active': True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0020_submission_revision_count_reopened_at'),
    ]

    operations = [
        migrations.RunPython(add_birth_date_question, noop),
    ]
