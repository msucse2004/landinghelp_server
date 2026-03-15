from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('settlement', '0028_schedule_plan_item_version_lineage'),
        ('survey', '0020_submission_revision_count_reopened_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='LsaSourcingBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('schedule_version', models.PositiveIntegerField(default=1, verbose_name='기준 일정 버전')),
                ('proposed_schedule_snapshot', models.JSONField(blank=True, default=list, verbose_name='제안 일정 스냅샷')),
                ('requested_services_snapshot', models.JSONField(blank=True, default=list, verbose_name='요청 서비스 스냅샷')),
                ('internal_pricing_snapshot', models.JSONField(blank=True, default=list, verbose_name='내부 단가 스냅샷')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_lsa_sourcing_batches', to=settings.AUTH_USER_MODEL, verbose_name='생성자')),
                ('schedule_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_sourcing_batches', to='settlement.servicescheduleplan', verbose_name='기준 일정 플랜')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_sourcing_batches', to='survey.surveysubmission', verbose_name='설문 제출')),
            ],
            options={
                'verbose_name': 'LSA 소싱 배치',
                'verbose_name_plural': 'LSA 소싱 배치',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='LsaAgentRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('SENT', '발송됨'), ('RESPONDED', '응답함'), ('DECLINED', '거절'), ('CANCELLED', '취소')], db_index=True, default='SENT', max_length=20, verbose_name='상태')),
                ('payload_snapshot', models.JSONField(blank=True, default=dict, verbose_name='발송 payload 스냅샷')),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('responded_at', models.DateTimeField(blank=True, null=True, verbose_name='응답 시각')),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agent_requests', to='settlement.lsasourcingbatch', verbose_name='LSA 배치')),
                ('target_agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_agent_requests', to=settings.AUTH_USER_MODEL, verbose_name='대상 Agent')),
            ],
            options={
                'verbose_name': 'LSA Agent 요청',
                'verbose_name_plural': 'LSA Agent 요청',
                'ordering': ['-sent_at'],
                'unique_together': {('batch', 'target_agent')},
            },
        ),
    ]
