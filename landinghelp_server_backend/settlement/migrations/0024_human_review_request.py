# HUMAN_REVIEW_REQUIRED 라우팅: 사람 검토 요청 모델

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('messaging', '0005_conversation_survey_submission'),
        ('survey', '0019_quote_change_request_models'),
        ('settlement', '0023_customer_action_offer'),
    ]

    operations = [
        migrations.CreateModel(
            name='HumanReviewRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('review_target', models.CharField(choices=[('admin', 'Admin 검토'), ('agent', 'Agent 검토'), ('admin_then_agent', 'Admin 후 Agent')], db_index=True, max_length=30, verbose_name='검토 담당')),
                ('status', models.CharField(choices=[('RECEIVED', '접수됨'), ('IN_REVIEW', '검토 중'), ('NEEDS_INFO', '추가 확인 필요'), ('COMPLETED', '답변 완료')], db_index=True, default='RECEIVED', max_length=20, verbose_name='상태')),
                ('original_message', models.TextField(blank=True, verbose_name='원문 메시지')),
                ('detected_intent', models.CharField(blank=True, db_index=True, max_length=80, verbose_name='LLM intent')),
                ('recommended_action', models.CharField(blank=True, max_length=80, verbose_name='recommended action')),
                ('execution_mode', models.CharField(blank=True, max_length=40, verbose_name='execution mode')),
                ('confidence', models.FloatField(default=0.0, verbose_name='confidence')),
                ('suggested_internal_next_step', models.TextField(blank=True, verbose_name='내부 권장 다음 단계')),
                ('suggested_customer_reply', models.TextField(blank=True, verbose_name='권장 고객 응답 문구')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='처리 완료 시각')),
                ('completed_note', models.TextField(blank=True, verbose_name='처리 메모')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('appointment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='human_review_requests', to='settlement.agentappointmentrequest', verbose_name='약속')),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_human_review_requests', to=settings.AUTH_USER_MODEL, verbose_name='담당자')),
                ('change_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='human_review_requests', to='settlement.quotechangerequest', verbose_name='변경 요청')),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='human_review_requests', to='messaging.conversation', verbose_name='대화')),
                ('quote', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='human_review_requests', to='settlement.settlementquote', verbose_name='견적')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='human_review_requests', to=settings.AUTH_USER_MODEL, verbose_name='요청자')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='human_review_requests', to='survey.surveysubmission', verbose_name='설문 제출')),
                ('trigger_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='triggered_human_review_requests', to='messaging.message', verbose_name='트리거 메시지')),
            ],
            options={
                'verbose_name': '사람 검토 요청',
                'verbose_name_plural': '사람 검토 요청',
                'ordering': ['-created_at'],
            },
        ),
    ]
