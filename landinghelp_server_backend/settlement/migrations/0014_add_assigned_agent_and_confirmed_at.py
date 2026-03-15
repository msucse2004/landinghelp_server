# 전담 Agent 배정 + Agent 일정 확정 필드

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("settlement", "0013_add_settlement_quote"),
    ]

    operations = [
        migrations.AddField(
            model_name="usersettlementplan",
            name="assigned_agent",
            field=models.ForeignKey(
                blank=True,
                help_text="결제 후 고객이 선택한 전담 Agent 1명. 서비스별 선택 제거.",
                null=True,
                on_delete=models.SET_NULL,
                related_name="assigned_customer_plans",
                to=settings.AUTH_USER_MODEL,
                verbose_name="전담 Agent",
            ),
        ),
        migrations.AddField(
            model_name="agentappointmentrequest",
            name="confirmed_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Agent가 일정(날짜/시간) 확정 시 기록. 확정 시 고객에게 메시지 발송.",
                null=True,
                verbose_name="일정 확정 시각",
            ),
        ),
        migrations.AddField(
            model_name="agentappointmentrequest",
            name="confirmed_time_slot",
            field=models.CharField(
                blank=True,
                help_text="Agent가 확정한 시간대(예: 10:00-12:00).",
                max_length=100,
                verbose_name="확정 시간대",
            ),
        ),
    ]
