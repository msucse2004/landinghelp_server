# Main Visa 소지자 이름 문항을 신청자 정보 → 입국 목적·체류 카드로 이동 (설문 일관성)

from django.db import migrations


def move_main_visa_holder_questions(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section = SurveySection.objects.filter(title='입국 목적·체류').first()
    if not section:
        return

    for i, key in enumerate(('main_visa_holder_first_name', 'main_visa_holder_last_name'), start=4):
        q = SurveyQuestion.objects.filter(key=key).first()
        if q:
            q.section = section
            q.step = section.display_order
            q.order_in_section = i
            q.order = i
            q.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0016_add_entry_date_question'),
    ]

    operations = [
        migrations.RunPython(move_main_visa_holder_questions, noop),
    ]
