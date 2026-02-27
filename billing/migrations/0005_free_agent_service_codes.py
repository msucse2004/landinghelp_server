# Generated migration: replace free_agent_services (count) with free_agent_service_codes (list)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_add_free_agent_services'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='free_agent_service_codes',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='고객 플랜 전용. 이 요금제에서 무료로 제공하는 정착 서비스 코드 목록. 예: ["AIRPORT_PICKUP"]',
                verbose_name='무료 Agent 서비스 항목',
            ),
        ),
        migrations.RemoveField(
            model_name='plan',
            name='free_agent_services',
        ),
    ]
