from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0026_alter_options_and_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicescheduleitem',
            name='needs_admin_review',
            field=models.BooleanField(default=False, verbose_name='Admin 검토 필요'),
        ),
        migrations.AddField(
            model_name='servicescheduleitem',
            name='recommendation_source',
            field=models.CharField(blank=True, default='fallback', help_text='historical | rule_based | fallback', max_length=30, verbose_name='추천 출처'),
        ),
    ]
