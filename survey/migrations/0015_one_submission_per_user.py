# 계정(user)당 설문 제출 1건만 허용. 기존 중복은 user_id 해제 후 제약 추가.

from django.db import migrations, models


def keep_one_submission_per_user(apps, schema_editor):
    """동일 user_id로 여러 건 있으면 최신 1건만 user 유지, 나머지는 user_id=NULL."""
    SurveySubmission = apps.get_model("survey", "SurveySubmission")
    from django.db.models import Max
    # user_id별로 최신 id 1개만 남기고 나머지의 user_id를 NULL로
    kept = (
        SurveySubmission.objects.filter(user_id__isnull=False)
        .values("user_id")
        .annotate(max_id=Max("id"))
        .values_list("user_id", "max_id")
    )
    for user_id, keep_id in kept:
        SurveySubmission.objects.filter(user_id=user_id).exclude(id=keep_id).update(user_id=None)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("survey", "0014_add_service_delivery_mode_question"),
    ]

    operations = [
        migrations.RunPython(keep_one_submission_per_user, noop),
        migrations.AddConstraint(
            model_name="surveysubmission",
            constraint=models.UniqueConstraint(
                condition=models.Q(user__isnull=False),
                fields=("user",),
                name="survey_one_submission_per_user",
            ),
        ),
    ]
