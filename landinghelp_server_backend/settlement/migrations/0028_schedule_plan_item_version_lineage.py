from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0027_schedule_item_recommendation_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicescheduleplan',
            name='based_on',
            field=models.ForeignKey(blank=True, help_text='Admin 조정안 버전이 어떤 이전 플랜을 기반으로 생성됐는지 추적.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='derived_plans', to='settlement.servicescheduleplan', verbose_name='기반 플랜'),
        ),
        migrations.AddField(
            model_name='servicescheduleitem',
            name='based_on_item',
            field=models.ForeignKey(blank=True, help_text='Admin 조정안에서 원본 system draft 항목 추적용.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='derived_items', to='settlement.servicescheduleitem', verbose_name='기반 항목'),
        ),
    ]
