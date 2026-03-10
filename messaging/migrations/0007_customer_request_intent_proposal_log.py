from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('messaging', '0006_add_customer_action_offer'),
        ('survey', '0020_submission_revision_count_reopened_at'),
        ('settlement', '0022_settlementquote_revision_superseded_at'),
    ]

    operations = [
        # ------------------------------------------------------------------
        # CustomerRequestIntentAnalysis
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name='CustomerRequestIntentAnalysis',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_text', models.TextField(help_text='고객이 입력한 원본 메시지.', verbose_name='원문 텍스트')),
                ('normalized_text', models.TextField(blank=True, help_text='전처리·정규화된 텍스트. 미사용 시 빈 값.', verbose_name='정규화 텍스트')),
                ('predicted_intent', models.CharField(
                    choices=[
                        ('SURVEY_REOPEN_REQUEST', '설문 재수정 요청'),
                        ('SURVEY_RESUME_REQUEST', '설문 이어쓰기 요청'),
                        ('QUOTE_RESEND_REQUEST', '견적 재발송 요청'),
                        ('QUOTE_ITEM_CHANGE_REQUEST', '견적 항목 변경 요청'),
                        ('SCHEDULE_CHANGE_REQUEST', '일정 변경 요청'),
                        ('AGENT_CHANGE_REQUEST', '담당자 변경 요청'),
                        ('PRICING_NEGOTIATION_REQUEST', '가격 협상 요청'),
                        ('GENERAL_QUESTION', '일반 문의'),
                        ('STATUS_CHECK', '진행 상태 확인'),
                        ('UNSUPPORTED_REQUEST', '미지원 요청'),
                    ],
                    db_index=True, max_length=60, verbose_name='분류된 의도',
                )),
                ('predicted_action', models.CharField(
                    choices=[
                        ('OFFER_SURVEY_REOPEN', '설문 재수정 제안'),
                        ('OFFER_SURVEY_RESUME', '설문 이어쓰기 제안'),
                        ('OFFER_QUOTE_RESEND', '견적 재발송 제안'),
                        ('OFFER_QUOTE_REVISION_REQUEST', '견적 수정 요청 제안'),
                        ('ROUTE_TO_ADMIN_REVIEW', 'Admin 검토 라우팅'),
                        ('ROUTE_TO_AGENT_REVIEW', 'Agent 검토 라우팅'),
                        ('ROUTE_TO_ADMIN_THEN_AGENT', 'Admin→Agent 라우팅'),
                        ('REPLY_WITH_INFORMATION', '정보 안내 응답'),
                        ('REPLY_WITH_STATUS', '상태 안내 응답'),
                    ],
                    db_index=True, max_length=60, verbose_name='제안 액션',
                )),
                ('execution_mode', models.CharField(
                    choices=[
                        ('AUTO_CONFIRMABLE', '자동 제안 (고객 확인)'),
                        ('HUMAN_REVIEW_REQUIRED', '사람 검토 필요'),
                        ('REPLY_ONLY', '응답만'),
                    ],
                    max_length=40, verbose_name='실행 모드',
                )),
                ('confidence', models.FloatField(default=0.0, help_text='0.0~1.0. LLM 또는 분류기 출력 confidence.', verbose_name='신뢰도')),
                ('source', models.CharField(
                    choices=[
                        ('heuristic', '휴리스틱 규칙'),
                        ('gemini', 'Gemini LLM'),
                        ('ollama', 'Ollama LLM'),
                        ('stub', 'Stub (미연동)'),
                        ('retrieval', '검색 기반'),
                        ('local_classifier', '로컬 분류기'),
                    ],
                    db_index=True, max_length=30, verbose_name='분류 소스',
                )),
                ('raw_model_output', models.JSONField(blank=True, help_text='LLM/분류기의 원시 JSON 응답. 디버그·감사용.', null=True, verbose_name='모델 원본 출력')),
                ('target_section_ids', models.JSONField(blank=True, help_text='LLM이 분석한 수정 대상 설문 섹션 ID 배열.', null=True, verbose_name='대상 설문 섹션')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='request_intent_analyses',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='고객',
                )),
                ('conversation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='intent_analyses',
                    to='messaging.conversation',
                    verbose_name='대화',
                )),
                ('message', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='intent_analyses',
                    to='messaging.message',
                    verbose_name='트리거 메시지',
                )),
            ],
            options={
                'verbose_name': '고객 요청 분류',
                'verbose_name_plural': '고객 요청 분류',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='customerrequestintentanalysis',
            index=models.Index(fields=['customer', '-created_at'], name='messaging_c_custome_7d3e4f_idx'),
        ),
        migrations.AddIndex(
            model_name='customerrequestintentanalysis',
            index=models.Index(fields=['conversation', '-created_at'], name='messaging_c_convers_a1b2c3_idx'),
        ),

        # ------------------------------------------------------------------
        # CustomerActionProposal
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name='CustomerActionProposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('proposal_type', models.CharField(
                    choices=[
                        ('SURVEY_REOPEN', '설문 재수정'),
                        ('SURVEY_RESUME', '설문 이어쓰기'),
                        ('QUOTE_RESEND', '견적 재발송'),
                        ('QUOTE_REVISION', '견적 수정 요청'),
                        ('HUMAN_REVIEW', '사람 검토 요청'),
                        ('INFO_REPLY', '정보 안내'),
                    ],
                    db_index=True, max_length=30, verbose_name='제안 유형',
                )),
                ('title', models.CharField(blank=True, max_length=200, verbose_name='제목')),
                ('body', models.TextField(blank=True, verbose_name='본문')),
                ('action_code', models.CharField(
                    db_index=True, max_length=80,
                    help_text='실행할 액션 식별자. 예: reopen_survey, resume_survey, resend_quote',
                    verbose_name='액션 코드',
                )),
                ('action_payload', models.JSONField(blank=True, default=dict, help_text='실행 시 필요한 추가 데이터 (submission_id, quote_id 등).', verbose_name='액션 파라미터')),
                ('status', models.CharField(
                    choices=[
                        ('PROPOSED', '제안됨'),
                        ('CONFIRMED', '고객 승인'),
                        ('DECLINED', '고객 거절'),
                        ('EXPIRED', '만료'),
                        ('EXECUTED', '실행 완료'),
                        ('FAILED', '실행 실패'),
                    ],
                    db_index=True, default='PROPOSED', max_length=20, verbose_name='상태',
                )),
                ('expires_at', models.DateTimeField(blank=True, null=True, verbose_name='만료 시각')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True, verbose_name='승인 시각')),
                ('declined_at', models.DateTimeField(blank=True, null=True, verbose_name='거절 시각')),
                ('executed_at', models.DateTimeField(blank=True, null=True, verbose_name='실행 시각')),
                ('failure_reason', models.TextField(blank=True, verbose_name='실패 사유')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('analysis', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='proposals',
                    to='messaging.customerrequestintentanalysis',
                    verbose_name='분류 결과',
                )),
                ('submission', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='action_proposals',
                    to='survey.surveysubmission',
                    verbose_name='설문 제출',
                )),
                ('quote', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='action_proposals',
                    to='settlement.settlementquote',
                    verbose_name='견적',
                )),
                ('conversation', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='action_proposals',
                    to='messaging.conversation',
                    verbose_name='대화',
                )),
                ('confirmed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='confirmed_proposals',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='승인자',
                )),
            ],
            options={
                'verbose_name': '고객 액션 제안',
                'verbose_name_plural': '고객 액션 제안',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='customeractionproposal',
            index=models.Index(fields=['status', '-created_at'], name='messaging_c_status_d4e5f6_idx'),
        ),
        migrations.AddIndex(
            model_name='customeractionproposal',
            index=models.Index(fields=['conversation', 'status'], name='messaging_c_convers_g7h8i9_idx'),
        ),

        # ------------------------------------------------------------------
        # CustomerActionFeedbackLog
        # ------------------------------------------------------------------
        migrations.CreateModel(
            name='CustomerActionFeedbackLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(
                    choices=[
                        ('PROPOSAL_SHOWN', '제안 노출'),
                        ('USER_CONFIRMED', '고객 승인'),
                        ('USER_DECLINED', '고객 거절'),
                        ('ACTION_STARTED', '액션 실행 시작'),
                        ('ACTION_SUCCEEDED', '액션 실행 성공'),
                        ('ACTION_FAILED', '액션 실행 실패'),
                        ('USER_CORRECTED', '고객 정정 요청'),
                        ('PROPOSAL_EXPIRED', '제안 만료'),
                        ('ADMIN_OVERRIDE', 'Admin 수동 처리'),
                    ],
                    db_index=True, max_length=30, verbose_name='이벤트 유형',
                )),
                ('event_payload', models.JSONField(blank=True, default=dict, help_text='이벤트별 상세 데이터. 실패 시 error, 정정 시 원문 등.', verbose_name='이벤트 데이터')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('proposal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='feedback_logs',
                    to='messaging.customeractionproposal',
                    verbose_name='제안',
                )),
                ('actor', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='action_feedback_logs',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='행위자',
                )),
            ],
            options={
                'verbose_name': '액션 피드백 로그',
                'verbose_name_plural': '액션 피드백 로그',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='customeractionfeedbacklog',
            index=models.Index(fields=['proposal', 'created_at'], name='messaging_c_proposa_j1k2l3_idx'),
        ),
    ]
