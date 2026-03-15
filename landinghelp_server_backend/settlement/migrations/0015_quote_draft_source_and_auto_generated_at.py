# 견적 초안 출처 및 자동 생성 시각 (자동 draft vs Admin 작성 구분)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settlement", "0014_add_assigned_agent_and_confirmed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="settlementquote",
            name="draft_source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "—"),
                    ("auto", "자동 생성"),
                    ("admin", "Admin 작성"),
                ],
                default="",
                help_text="자동 생성 draft vs Admin이 직접 작성·수정한 견적 구분.",
                max_length=10,
                verbose_name="초안 출처",
            ),
        ),
        migrations.AddField(
            model_name="settlementquote",
            name="auto_generated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="자동 생성 시각"),
        ),
    ]
