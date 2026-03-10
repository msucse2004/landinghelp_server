# 견적 변경 요청: 구조화 요청 + LLM 해석 + 실행 로그

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('survey', '0001_initial_survey_models'),
        ('settlement', '0020_schedule_domain_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='QuoteChangeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(choices=[('TEXT', '자유 텍스트'), ('STRUCTURED', '구조화'), ('MIXED', '혼합')], db_index=True, default='TEXT', max_length=20, verbose_name='입력 유형')),
                ('status', models.CharField(choices=[('OPEN', '접수'), ('ANALYZED', '분석 완료'), ('IN_REVIEW', '검토 중'), ('APPROVED', '승인'), ('REJECTED', '반려'), ('CUSTOMER_ACTION_REQUIRED', '고객 조치 대기'), ('APPLIED', '적용 완료'), ('CANCELED', '취소')], db_index=True, default='OPEN', max_length=30, verbose_name='상태')),
                ('customer_message', models.TextField(blank=True, verbose_name='고객 메시지')),
                ('admin_note', models.TextField(blank=True, verbose_name='Admin 메모')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='검토 시각')),
                ('resolved_at', models.DateTimeField(blank=True, null=True, verbose_name='처리 완료 시각')),
                ('quote', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='change_requests', to='settlement.settlementquote', verbose_name='대상 견적')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quote_change_requests', to=settings.AUTH_USER_MODEL, verbose_name='요청자')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='quote_change_requests', to='survey.surveysubmission', verbose_name='설문 제출')),
            ],
            options={
                'verbose_name': '견적 변경 요청',
                'verbose_name_plural': '견적 변경 요청',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='QuoteChangeRequestItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('ADD', '추가'), ('REMOVE', '제거'), ('CHANGE', '변경')], db_index=True, max_length=20, verbose_name='액션 유형')),
                ('service_code', models.CharField(blank=True, db_index=True, max_length=50, verbose_name='서비스 코드')),
                ('service_label', models.CharField(blank=True, max_length=200, verbose_name='서비스 표시명')),
                ('payload', models.JSONField(blank=True, default=dict, verbose_name='추가 데이터')),
                ('display_order', models.PositiveIntegerField(default=0, verbose_name='표시 순서')),
                ('change_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='settlement.quotechangerequest', verbose_name='변경 요청')),
            ],
            options={
                'verbose_name': '견적 변경 요청 항목',
                'verbose_name_plural': '견적 변경 요청 항목',
                'ordering': ['change_request', 'display_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='QuoteChangeAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('model_name', models.CharField(blank=True, max_length=100, verbose_name='LLM 모델명')),
                ('raw_customer_message', models.TextField(verbose_name='원문 고객 메시지')),
                ('normalized_summary', models.TextField(blank=True, verbose_name='정규화 요약')),
                ('detected_intent', models.CharField(choices=[('QUOTE_ITEM_CHANGE_REQUEST', '견적 항목 변경 요청'), ('SURVEY_REOPEN_REQUEST', '설문 재개 요청'), ('GENERAL_QUESTION', '일반 문의'), ('UNSUPPORTED_REQUEST', '미지원 요청'), ('URGENT_ADMIN_REVIEW', 'Admin 수동 검토')], db_index=True, max_length=40, verbose_name='감지된 의도')),
                ('confidence', models.FloatField(default=0.0, help_text='0.0~1.0. 이 값이 낮으면 수동 검토 권장.', verbose_name='신뢰도')),
                ('extracted_actions', models.JSONField(blank=True, default=list, help_text='[{"action": "PROPOSE_ADD_SERVICE", "service_code": "X", ...}, ...]', verbose_name='추출된 액션 목록')),
                ('extracted_service_codes', models.JSONField(blank=True, default=list, verbose_name='추출된 서비스 코드 목록')),
                ('requires_admin_confirmation', models.BooleanField(default=True, verbose_name='Admin 확인 필요')),
                ('recommended_next_step', models.CharField(blank=True, max_length=500, verbose_name='추천 다음 단계')),
                ('raw_llm_output', models.JSONField(blank=True, default=dict, verbose_name='LLM 원시 출력')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('change_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='analyses', to='settlement.quotechangerequest', verbose_name='변경 요청')),
            ],
            options={
                'verbose_name': '견적 변경 LLM 분석',
                'verbose_name_plural': '견적 변경 LLM 분석',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='QuoteChangeActionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action_type', models.CharField(choices=[('ANALYSIS_CREATED', '분석 생성'), ('ADMIN_APPROVED_REOPEN', 'Admin 설문 재개 승인'), ('ADMIN_APPROVED_QUOTE_REVISION', 'Admin 견적 수정 승인'), ('ADMIN_REJECTED', 'Admin 반려'), ('SURVEY_REOPENED', '설문 재개 실행'), ('QUOTE_SUPERSEDED', '견적 대체(수정본 생성)'), ('MESSAGE_SENT', '메시지 발송'), ('CUSTOMER_RESUME_LINK_CREATED', '고객 설문 링크 생성')], db_index=True, max_length=50, verbose_name='액션 유형')),
                ('detail', models.JSONField(blank=True, default=dict, verbose_name='상세')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='quote_change_action_logs', to=settings.AUTH_USER_MODEL, verbose_name='실행자')),
                ('change_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='action_logs', to='settlement.quotechangerequest', verbose_name='변경 요청')),
            ],
            options={
                'verbose_name': '견적 변경 액션 로그',
                'verbose_name_plural': '견적 변경 액션 로그',
                'ordering': ['-created_at'],
            },
        ),
    ]
