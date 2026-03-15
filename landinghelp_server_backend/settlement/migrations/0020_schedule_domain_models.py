# Step 5: 스케줄 도메인 모델 — ServiceSchedulePlan, ServiceScheduleItem, AgentAvailabilityWindow
# ML 초안/Admin 수정/확정 이력 분리. 기존 UserSettlementPlan.service_schedule JSON 유지(하위 호환).

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('survey', '0001_initial_survey_models'),  # SurveySubmission
        ('settlement', '0019_service_state_price'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceSchedulePlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('DRAFT', '초안'), ('REVIEWING', '검토 중'), ('FINALIZED', '확정'), ('SENT', '고객 송부'), ('ACTIVE', '활성(달력 반영)')], db_index=True, default='DRAFT', max_length=20, verbose_name='상태')),
                ('source', models.CharField(blank=True, choices=[('ML', 'ML 추천'), ('ADMIN', 'Admin 작성'), ('HYBRID', 'ML+Admin 혼합')], default='ADMIN', max_length=20, verbose_name='출처')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='버전')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_schedule_plans', to=settings.AUTH_USER_MODEL, verbose_name='생성자')),
                ('customer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='service_schedule_plans', to=settings.AUTH_USER_MODEL, verbose_name='고객')),
                ('quote', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='service_schedule_plans', to='settlement.settlementquote', verbose_name='견적')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='service_schedule_plans', to='survey.surveysubmission', verbose_name='설문 제출')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_schedule_plans', to=settings.AUTH_USER_MODEL, verbose_name='수정자')),
            ],
            options={
                'verbose_name': '서비스 일정 플랜',
                'verbose_name_plural': '서비스 일정 플랜',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='ServiceScheduleItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_code', models.CharField(max_length=50, verbose_name='서비스 코드')),
                ('service_label', models.CharField(blank=True, max_length=200, verbose_name='서비스 표시명')),
                ('service_type', models.CharField(blank=True, choices=[('SELF_SEARCH', '직접 검색'), ('AI_AGENT', 'AI 서비스'), ('IN_PERSON_AGENT', 'Agent 대면')], default='AI_AGENT', max_length=30, verbose_name='서비스 유형')),
                ('starts_at', models.DateTimeField(blank=True, null=True, verbose_name='시작 시각')),
                ('ends_at', models.DateTimeField(blank=True, null=True, verbose_name='종료 시각')),
                ('duration_minutes', models.PositiveIntegerField(blank=True, null=True, verbose_name='소요 시간(분)')),
                ('location_text', models.CharField(blank=True, max_length=300, verbose_name='장소/위치')),
                ('status', models.CharField(choices=[('SCHEDULED', '예정'), ('CONFIRMED', '확정'), ('CANCELLED', '취소')], db_index=True, default='SCHEDULED', max_length=20, verbose_name='상태')),
                ('source_score', models.DecimalField(blank=True, decimal_places=2, help_text='ML 생성 시 신뢰도/점수.', max_digits=5, null=True, verbose_name='ML 추천 점수')),
                ('source_reason', models.CharField(blank=True, help_text='ML/Admin 선택 이유 요약.', max_length=500, verbose_name='출처 사유')),
                ('notes', models.TextField(blank=True, verbose_name='메모')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='정렬 순서')),
                ('assigned_agent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_schedule_items', to=settings.AUTH_USER_MODEL, verbose_name='배정 Agent')),
                ('schedule_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='settlement.servicescheduleplan', verbose_name='일정 플랜')),
            ],
            options={
                'verbose_name': '서비스 일정 항목',
                'verbose_name_plural': '서비스 일정 항목',
                'ordering': ['schedule_plan', 'sort_order', 'starts_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='AgentAvailabilityWindow',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('starts_at', models.DateTimeField(verbose_name='시작 시각')),
                ('ends_at', models.DateTimeField(verbose_name='종료 시각')),
                ('source', models.CharField(choices=[('manual', '직접 입력'), ('link_response', '링크 응답'), ('admin_entered', 'Admin 입력')], default='manual', max_length=20, verbose_name='입력 출처')),
                ('status', models.CharField(choices=[('AVAILABLE', '가능'), ('USED', '사용됨'), ('CANCELLED', '취소')], db_index=True, default='AVAILABLE', max_length=20, verbose_name='상태')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availability_windows', to=settings.AUTH_USER_MODEL, verbose_name='Agent')),
                ('schedule_plan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='agent_availability_windows', to='settlement.servicescheduleplan', verbose_name='일정 플랜')),
                ('submission', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='agent_availability_windows', to='survey.surveysubmission', verbose_name='설문 제출')),
            ],
            options={
                'verbose_name': 'Agent 가용 시간대',
                'verbose_name_plural': 'Agent 가용 시간대',
                'ordering': ['agent', 'starts_at'],
            },
        ),
    ]
