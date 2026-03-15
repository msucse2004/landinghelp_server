from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0036_internal_availability_workflow'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceCompletionForm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('SUBMITTED', '제출됨'), ('REVIEWED', '내부 검토 완료')], db_index=True, default='SUBMITTED', max_length=20, verbose_name='상태')),
                ('summary', models.CharField(blank=True, max_length=300, verbose_name='완료 요약')),
                ('completion_notes', models.TextField(blank=True, verbose_name='완료 노트')),
                ('attachments_count', models.PositiveIntegerField(default=0, verbose_name='첨부 개수')),
                ('submitted_at', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='제출 시각')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='검토 시각')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_completion_forms', to=settings.AUTH_USER_MODEL, verbose_name='Agent')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_service_completion_forms', to=settings.AUTH_USER_MODEL, verbose_name='검토자')),
                ('schedule_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_completion_forms', to='settlement.servicescheduleplan', verbose_name='일정 플랜')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_completion_forms', to='survey.surveysubmission', verbose_name='설문 제출')),
            ],
            options={
                'verbose_name': '서비스 완료 보고서',
                'verbose_name_plural': '서비스 완료 보고서',
                'ordering': ['-submitted_at', '-created_at'],
                'unique_together': {('submission', 'agent', 'schedule_plan')},
            },
        ),
        migrations.AddIndex(
            model_name='servicecompletionform',
            index=models.Index(fields=['submission', 'status'], name='settlement_s_submiss_002f43_idx'),
        ),
        migrations.AddIndex(
            model_name='servicecompletionform',
            index=models.Index(fields=['agent', 'status'], name='settlement_s_agent_i_761f57_idx'),
        ),
    ]
