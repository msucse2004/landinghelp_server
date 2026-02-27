# Add Plan.duration_months (요금제 유지 기간)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_free_agent_service_codes'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='duration_months',
            field=models.IntegerField(
                choices=[(1, '1개월'), (3, '3개월'), (6, '6개월'), (0, '무제한')],
                default=1,
                help_text='1개월, 3개월, 6개월, 무제한 중 선택.',
                verbose_name='요금제 유지 기간',
            ),
        ),
    ]
