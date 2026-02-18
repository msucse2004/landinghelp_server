# Migration: Plan target_role PROVIDER → AGENT

from django.db import migrations


def provider_to_agent(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(target_role='PROVIDER').update(target_role='AGENT')


def agent_to_provider(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(target_role='AGENT').update(target_role='PROVIDER')


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_plan_subscription_new_schema'),
    ]

    operations = [
        migrations.RunPython(provider_to_agent, agent_to_provider),
    ]
