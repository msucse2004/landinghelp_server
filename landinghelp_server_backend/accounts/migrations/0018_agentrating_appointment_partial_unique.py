# AgentRating: add appointment FK, replace unique with per-appointment / legacy per (rater,agent)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_preferred_language_default_en'),
        ('settlement', '0011_agentappointmentrequest_cancellation_reason'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentrating',
            name='appointment',
            field=models.ForeignKey(
                blank=True,
                help_text='완료된 약속에 대한 후기일 때만 연결. 약속당 1건만 허용.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='ratings',
                to='settlement.agentappointmentrequest',
                verbose_name='연결된 약속',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='agentrating',
            name='unique_agent_rating_per_customer',
        ),
        migrations.AddConstraint(
            model_name='agentrating',
            constraint=models.UniqueConstraint(
                condition=models.Q(appointment__isnull=True),
                fields=('rater', 'agent'),
                name='unique_agent_rating_per_customer_legacy',
            ),
        ),
        migrations.AddConstraint(
            model_name='agentrating',
            constraint=models.UniqueConstraint(
                condition=models.Q(appointment__isnull=False),
                fields=('rater', 'appointment'),
                name='unique_agent_rating_per_appointment',
            ),
        ),
    ]
