# 기본 선호 언어를 en으로 통일 (로그인 시 한글 대신 영어 표시)
from django.db import migrations, models


def set_missing_or_ko_to_en(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(preferred_language__in=("", "ko")).update(preferred_language="en")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_add_preferred_language"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="preferred_language",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ko", "KR 한국어"),
                    ("en", "EN English"),
                    ("es", "ES Español"),
                    ("zh-hans", "ZH 中文(简体)"),
                    ("zh-hant", "ZH 中文(繁體)"),
                    ("vi", "VI Tiếng Việt"),
                ],
                default="en",
                max_length=10,
                verbose_name="선호 언어",
            ),
        ),
        migrations.RunPython(set_missing_or_ko_to_en, migrations.RunPython.noop),
    ]
