# 서비스 진행 방식을 기타 의뢰 내용보다 먼저 오도록 순서 조정 (희망 서비스 직후)

from django.db import migrations


def reorder_sections(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveySection.objects.filter(title='서비스 진행 방식').update(display_order=6)
    SurveySection.objects.filter(title='기타 의뢰 내용').update(display_order=7)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0012_add_service_delivery_preference_section'),
    ]

    operations = [
        migrations.RunPython(reorder_sections, noop),
    ]
