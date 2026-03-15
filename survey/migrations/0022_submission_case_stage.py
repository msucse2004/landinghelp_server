from django.db import migrations, models
from django.utils import timezone


def forward_fill_case_stage(apps, schema_editor):
    SurveySubmission = apps.get_model('survey', 'SurveySubmission')

    stage_by_status = {
        'DRAFT': 'SURVEY_IN_PROGRESS',
        'REVISION_REQUESTED': 'SURVEY_IN_PROGRESS',
        'SUBMITTED': 'QUOTE_PREPARING',
        'AWAITING_PAYMENT': 'QUOTE_SENT',
        'AGENT_ASSIGNMENT': 'PAYMENT_COMPLETED',
        'SERVICE_IN_PROGRESS': 'SERVICES_IN_PROGRESS',
    }

    now = timezone.now()
    for status, stage in stage_by_status.items():
        SurveySubmission.objects.filter(status=status).update(
            case_stage=stage,
            case_stage_updated_at=now,
        )


def backward_fill_case_stage(apps, schema_editor):
    SurveySubmission = apps.get_model('survey', 'SurveySubmission')
    SurveySubmission.objects.update(
        case_stage='SURVEY_IN_PROGRESS',
        case_stage_updated_at=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0021_add_birth_date_question'),
    ]

    operations = [
        migrations.AddField(
            model_name='surveysubmission',
            name='case_stage',
            field=models.CharField(
                choices=[
                    ('SURVEY_IN_PROGRESS', '설문 진행중'),
                    ('QUOTE_PREPARING', '견적 준비중'),
                    ('QUOTE_SENT', '견적 송부'),
                    ('QUOTE_ACCEPTED', '견적 수락'),
                    ('CONTRACT_PACKAGE_SENT', '계약 패키지 송부'),
                    ('CONTRACT_FULLY_SIGNED', '계약 서명 완료'),
                    ('PAYMENT_COMPLETED', '결제 완료'),
                    ('AVAILABILITY_REQUESTED', '가용시간 요청'),
                    ('LSA_PENDING', 'LSA 진행중'),
                    ('SCHEDULE_FINALIZED', '일정 확정'),
                    ('SERVICES_IN_PROGRESS', '서비스 진행중'),
                    ('SERVICE_COMPLETED', '서비스 완료'),
                    ('CLOSED', '종료'),
                ],
                db_index=True,
                default='SURVEY_IN_PROGRESS',
                help_text='설문 status와 분리된 전체 비즈니스 워크플로우 단계.',
                max_length=40,
                verbose_name='케이스 단계',
            ),
        ),
        migrations.AddField(
            model_name='surveysubmission',
            name='case_stage_updated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='케이스 단계 갱신 시각'),
        ),
        migrations.RunPython(forward_fill_case_stage, backward_fill_case_stage),
    ]
