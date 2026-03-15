# Survey card/section + question metadata (Step 1 card-based builder)
# Reuses SurveyQuestion/SurveySubmission; no data removal.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("survey", "0002_add_last_reminded_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveySection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200, verbose_name="카드 제목")),
                ("description", models.TextField(blank=True, verbose_name="카드 설명/도움말")),
                ("display_order", models.PositiveIntegerField(default=0, verbose_name="표시 순서")),
                ("is_active", models.BooleanField(default=True, verbose_name="활성")),
                (
                    "is_internal",
                    models.BooleanField(
                        default=False,
                        help_text="True면 고객 설문에 노출되지 않음(내부용).",
                        verbose_name="Admin 전용",
                    ),
                ),
                (
                    "visibility_condition",
                    models.JSONField(
                        blank=True,
                        null=True,
                        help_text='선택. 예: {"depends_on": "question_key", "value": "expected"}',
                        verbose_name="조건부 노출",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "설문 카드(섹션)",
                "verbose_name_plural": "설문 카드(섹션)",
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.AddField(
            model_name="surveyquestion",
            name="section",
            field=models.ForeignKey(
                blank=True,
                help_text="비어 있으면 기존 step/order로만 사용.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="questions",
                to="survey.surveysection",
                verbose_name="소속 카드(섹션)",
            ),
        ),
        migrations.AddField(
            model_name="surveyquestion",
            name="order_in_section",
            field=models.PositiveIntegerField(
                default=0,
                help_text="같은 카드 안에서의 표시 순서.",
                verbose_name="카드 내 순서",
            ),
        ),
        migrations.AddField(
            model_name="surveyquestion",
            name="placeholder",
            field=models.CharField(
                blank=True,
                help_text="입력 필드 placeholder 텍스트.",
                max_length=200,
                verbose_name="placeholder",
            ),
        ),
        migrations.AddField(
            model_name="surveyquestion",
            name="quote_relevant",
            field=models.BooleanField(
                default=False,
                help_text="True면 자동 견적 초안 생성 시 이 답변을 참고.",
                verbose_name="견적 반영",
            ),
        ),
    ]
