# Generated migration file

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_agentrating_appointment_partial_unique'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='agentforrating',
            options={'ordering': ['agent__username'], 'verbose_name': '에이전트 평가 대상', 'verbose_name_plural': '에이전트 평가 대상'},
        ),
        migrations.AlterModelOptions(
            name='agentrating',
            options={'ordering': ['-created_at'], 'verbose_name': '에이전트 평가', 'verbose_name_plural': '에이전트 평가'},
        ),
        migrations.AlterModelOptions(
            name='user',
            options={'ordering': ['-date_joined'], 'verbose_name': '사용자', 'verbose_name_plural': '사용자'},
        ),
    ]
