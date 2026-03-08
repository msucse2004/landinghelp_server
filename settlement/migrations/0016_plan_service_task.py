# Step 10: Post-payment scheduling - required tasks from approved quote

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("settlement", "0015_quote_draft_source_and_auto_generated_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlanServiceTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service_code", models.CharField(max_length=50, verbose_name="서비스 코드")),
                ("label", models.CharField(blank=True, max_length=200, verbose_name="표시명")),
                ("display_order", models.PositiveIntegerField(default=0, verbose_name="표시 순서")),
                (
                    "appointment",
                    models.OneToOneField(
                        blank=True,
                        help_text="고객/Admin이 에이전트 배정 후 생성된 약속.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="plan_task",
                        to="settlement.agentappointmentrequest",
                        verbose_name="연결된 약속",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_tasks",
                        to="settlement.usersettlementplan",
                        verbose_name="정착 플랜",
                    ),
                ),
            ],
            options={
                "verbose_name": "플랜 서비스 작업",
                "verbose_name_plural": "플랜 서비스 작업",
                "ordering": ["display_order", "id"],
                "unique_together": {("plan", "service_code")},
            },
        ),
    ]
