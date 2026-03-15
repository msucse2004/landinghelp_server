# Migration: PROVIDER → AGENT 역할 변경

from django.db import migrations


def provider_to_agent(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='PROVIDER').update(role='AGENT')


def agent_to_provider(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='AGENT').update(role='PROVIDER')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_add_unverified_status'),
    ]

    operations = [
        migrations.RunPython(provider_to_agent, agent_to_provider),
    ]
