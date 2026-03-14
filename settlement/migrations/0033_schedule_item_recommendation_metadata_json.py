from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0032_lsa_contract_execution_plan'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicescheduleitem',
            name='recommendation_metadata',
            field=models.JSONField(blank=True, default=dict, help_text='confidence/evidence_type/sample_count/day_offset 등 구조화된 추천 근거.', verbose_name='추천 메타데이터'),
        ),
    ]
