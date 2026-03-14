from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0030_lsa_agent_response_models'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('survey', '0020_submission_revision_count_reopened_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='lsasourcingbatch',
            name='closed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='배치 종료 시각'),
        ),
        migrations.AddField(
            model_name='lsasourcingbatch',
            name='selected_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='선정 시각'),
        ),
        migrations.AddField(
            model_name='lsasourcingbatch',
            name='selected_request',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='selected_for_batch', to='settlement.lsaagentrequest', verbose_name='선정된 Agent 요청'),
        ),
        migrations.AlterField(
            model_name='lsaagentrequest',
            name='status',
            field=models.CharField(choices=[('SENT', '발송됨'), ('RESPONDED', '응답함'), ('DECLINED', '거절'), ('SELECTED', '선정됨'), ('NOT_SELECTED', '미선정'), ('CANCELLED', '취소')], db_index=True, default='SENT', max_length=20, verbose_name='상태'),
        ),
        migrations.CreateModel(
            name='LsaAgentContract',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('selection_note', models.TextField(blank=True, verbose_name='선정 메모')),
                ('audit_payload', models.JSONField(blank=True, default=dict, verbose_name='감사 추적 payload')),
                ('selected_at', models.DateTimeField(auto_now_add=True, verbose_name='선정 시각')),
                ('batch', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='contract', to='settlement.lsasourcingbatch', verbose_name='LSA 배치')),
                ('schedule_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_agent_contracts', to='settlement.servicescheduleplan', verbose_name='일정 플랜')),
                ('selected_agent', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='selected_lsa_contracts', to=settings.AUTH_USER_MODEL, verbose_name='선정 Agent')),
                ('selected_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_lsa_contracts', to=settings.AUTH_USER_MODEL, verbose_name='선정 Admin')),
                ('selected_request', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='contracts', to='settlement.lsaagentrequest', verbose_name='선정 요청')),
                ('selected_response', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contracts', to='settlement.lsaagentresponse', verbose_name='선정 응답')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_agent_contracts', to='survey.surveysubmission', verbose_name='설문 제출')),
            ],
            options={
                'verbose_name': 'LSA Agent 계약',
                'verbose_name_plural': 'LSA Agent 계약',
                'ordering': ['-selected_at'],
            },
        ),
    ]
