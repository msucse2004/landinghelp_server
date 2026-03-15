# Migration: Content allowed_roles 내 PROVIDER → AGENT

from django.db import migrations


def provider_to_agent(apps, schema_editor):
    Content = apps.get_model('content', 'Content')
    for c in Content.objects.all():
        if isinstance(c.allowed_roles, list) and 'PROVIDER' in c.allowed_roles:
            c.allowed_roles = ['AGENT' if r == 'PROVIDER' else r for r in c.allowed_roles]
            c.save()


def agent_to_provider(apps, schema_editor):
    Content = apps.get_model('content', 'Content')
    for c in Content.objects.all():
        if isinstance(c.allowed_roles, list) and 'AGENT' in c.allowed_roles:
            c.allowed_roles = ['PROVIDER' if r == 'AGENT' else r for r in c.allowed_roles]
            c.save()


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0002_option_a_schema'),
    ]

    operations = [
        migrations.RunPython(provider_to_agent, agent_to_provider),
    ]
