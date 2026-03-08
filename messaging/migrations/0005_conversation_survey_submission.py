# 설문 제출/견적 알림 공지 대화에서 고객 설문 확인 링크용

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0004_add_message_translation"),
        ("survey", "0001_initial_survey_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="survey_submission",
            field=models.ForeignKey(
                blank=True,
                help_text="공지 대화가 설문 제출/견적 알림일 때 연결된 제출 건.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="conversations",
                to="survey.surveysubmission",
                verbose_name="설문 제출",
            ),
        ),
    ]
