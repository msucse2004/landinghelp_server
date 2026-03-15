# Step 5: Quote automation - question metadata (quote_mapping_key, quote_value_type)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("survey", "0004_request_dossier_revision_and_events"),
    ]

    operations = [
        migrations.AddField(
            model_name="surveyquestion",
            name="quote_mapping_key",
            field=models.CharField(
                blank=True,
                help_text="견적 입력 정규화용 캐노니컬 키. service_codes, region, entry_date, household_size, add_on_codes, special_requirements 등.",
                max_length=50,
                verbose_name="견적 매핑 키",
            ),
        ),
        migrations.AddField(
            model_name="surveyquestion",
            name="quote_value_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "—"),
                    ("service_codes", "서비스 코드 목록"),
                    ("region", "지역(문자열)"),
                    ("date", "날짜(YYYY-MM-DD)"),
                    ("number", "숫자"),
                    ("options", "선택값(단일/다중)"),
                    ("text", "자유 텍스트"),
                ],
                default="",
                help_text="답변을 어떻게 해석할지. 정규화 시 참고.",
                max_length=20,
                verbose_name="견적 값 유형",
            ),
        ),
    ]
