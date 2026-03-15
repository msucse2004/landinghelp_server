from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0031_lsa_batch_contract_selection'),
    ]

    operations = [
        migrations.AddField(
            model_name='lsaagentcontract',
            name='execution_schedule_plan',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='execution_contract', to='settlement.servicescheduleplan', verbose_name='최종 실행 일정 플랜'),
        ),
    ]
