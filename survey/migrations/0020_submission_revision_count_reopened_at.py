# Admin 설문 재개 승인: revision_count, reopened_at

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0019_quote_change_request_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='surveysubmission',
            name='revision_count',
            field=models.PositiveIntegerField(
                default=0,
                help_text='Admin이 설문 재개를 승인한 횟수. 재제출 시 리셋하지 않음.',
                verbose_name='수정 재개 횟수',
            ),
        ),
        migrations.AddField(
            model_name='surveysubmission',
            name='reopened_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Admin이 설문 수정을 승인한 시각.',
                null=True,
                verbose_name='최근 재개 시각',
            ),
        ),
        migrations.AlterField(
            model_name='surveysubmissionevent',
            name='event_type',
            field=models.CharField(
                choices=[
                    ('submitted', '제출'),
                    ('revision_requested', '수정 요청'),
                    ('reopened', '재개 승인'),
                    ('sections_update_requested', '카드별 수정 요청'),
                    ('resubmitted', '재제출'),
                    ('quote_sent', '견적 송부'),
                    ('paid', '결제 완료'),
                    ('schedule_sent', '일정 송부'),
                ],
                max_length=30,
                verbose_name='이벤트',
            ),
        ),
    ]
