# 통합 도메인 서비스: 고객 액션 제안(버튼) 모델

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('messaging', '0005_conversation_survey_submission'),
        ('survey', '0019_quote_change_request_models'),
        ('settlement', '0022_settlementquote_revision_superseded_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerActionOffer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=200, verbose_name='제목')),
                ('body', models.TextField(blank=True, verbose_name='본문')),
                ('button_label', models.CharField(max_length=100, verbose_name='버튼 라벨')),
                ('button_action_key', models.CharField(db_index=True, help_text='예: survey_reopen, survey_resume, quote_resend', max_length=80, verbose_name='버튼 액션 키')),
                ('expires_at', models.DateTimeField(blank=True, null=True, verbose_name='만료 시각')),
                ('status', models.CharField(choices=[('PENDING', '대기'), ('EXECUTED', '실행됨'), ('EXPIRED', '만료'), ('CANCELED', '취소')], db_index=True, default='PENDING', max_length=20, verbose_name='상태')),
                ('can_execute', models.BooleanField(default=True, help_text='서버에서 판단한 실행 가능 여부.', verbose_name='실행 가능')),
                ('executed_at', models.DateTimeField(blank=True, null=True, verbose_name='실행 시각')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('change_request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='action_offers', to='settlement.quotechangerequest', verbose_name='변경 요청')),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='action_offers', to='messaging.conversation', verbose_name='대화')),
                ('executed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='executed_action_offers', to=settings.AUTH_USER_MODEL, verbose_name='실행자')),
                ('quote', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='action_offers', to='settlement.settlementquote', verbose_name='견적')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='action_offers', to='survey.surveysubmission', verbose_name='설문 제출')),
                ('trigger_message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='triggered_action_offers', to='messaging.message', verbose_name='트리거 메시지')),
            ],
            options={
                'verbose_name': '고객 액션 제안',
                'verbose_name_plural': '고객 액션 제안',
                'ordering': ['-created_at'],
            },
        ),
    ]
