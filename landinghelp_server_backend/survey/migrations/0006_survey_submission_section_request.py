# Step 8: Section-level update requests (admin marks sections, customer revises those only)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("survey", "0005_quote_metadata_for_automation"),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveySubmissionSectionRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField(blank=True, help_text="해당 카드에 대한 안내(선택).", verbose_name="요청 메시지")),
                ("requested_at", models.DateTimeField(auto_now_add=True, verbose_name="요청 시각")),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="해결 시각", help_text="고객 수정·재제출 시 설정.")),
                ("section", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="submission_requests", to="survey.surveysection", verbose_name="수정 요청 카드")),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="section_requests", to="survey.surveysubmission", verbose_name="설문 제출")),
                ("requested_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="survey_section_requests", to=settings.AUTH_USER_MODEL, verbose_name="요청자")),
            ],
            options={
                "verbose_name": "제출 카드별 수정 요청",
                "verbose_name_plural": "제출 카드별 수정 요청",
                "ordering": ["section__display_order", "id"],
            },
        ),
    ]
