# SettlementQuote: Admin 작성 견적 (설문 제출 연결)

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settlement", "0012_add_reminder_sent_at"),
        ("survey", "0002_add_last_reminded_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="SettlementQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(
                    choices=[
                        ("DRAFT", "초안"),
                        ("NEGOTIATING", "협의 중"),
                        ("FINAL_SENT", "송부 완료"),
                        ("PAID", "결제 완료"),
                    ],
                    db_index=True,
                    default="DRAFT",
                    max_length=20,
                    verbose_name="상태",
                )),
                ("items", models.JSONField(
                    blank=True,
                    default=list,
                    help_text='예: [{"code":"X","label":"서비스명","price":50000}, ...]',
                    verbose_name="견적 항목",
                )),
                ("region", models.CharField(blank=True, max_length=200, verbose_name="지역")),
                ("total", models.DecimalField(
                    decimal_places=0,
                    default=Decimal("0"),
                    max_digits=14,
                    verbose_name="합계",
                )),
                ("version", models.PositiveIntegerField(default=1, verbose_name="버전")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True, verbose_name="송부 시각")),
                ("submission", models.ForeignKey(
                    on_delete=models.CASCADE,
                    related_name="settlement_quotes",
                    to="survey.surveysubmission",
                    verbose_name="설문 제출",
                )),
            ],
            options={
                "verbose_name": "견적",
                "verbose_name_plural": "견적",
                "ordering": ["-updated_at"],
            },
        ),
    ]
