# Step 4: Request dossier - revision requested + event audit trail

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("survey", "0003_survey_section_and_question_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="surveysubmission",
            name="revision_requested_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Admin이 고객에게 수정을 요청한 시각.",
                null=True,
                verbose_name="수정 요청 시각",
            ),
        ),
        migrations.AddField(
            model_name="surveysubmission",
            name="revision_requested_message",
            field=models.TextField(
                blank=True,
                help_text="고객에게 전달할 수정 요청 안내(선택).",
                verbose_name="수정 요청 메시지",
            ),
        ),
        migrations.CreateModel(
            name="SurveySubmissionEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("submitted", "제출"),
                            ("revision_requested", "수정 요청"),
                            ("resubmitted", "재제출"),
                            ("quote_sent", "견적 송부"),
                            ("paid", "결제 완료"),
                        ],
                        max_length=30,
                        verbose_name="이벤트",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="발생 시각")),
                ("meta", models.JSONField(blank=True, default=dict, help_text='예: {"message": "입력일 수정 요청"}', verbose_name="메타")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="survey_submission_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="작업자",
                    ),
                ),
                (
                    "submission",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="survey.surveysubmission",
                        verbose_name="설문 제출",
                    ),
                ),
            ],
            options={
                "verbose_name": "제출 이벤트",
                "verbose_name_plural": "제출 이벤트",
                "ordering": ["-created_at"],
            },
        ),
    ]
