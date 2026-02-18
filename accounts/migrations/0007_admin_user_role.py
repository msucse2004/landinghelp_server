# Migration: admin 아이디 및 슈퍼유저의 역할을 ADMIN으로 설정

from django.db import migrations


def set_admin_role(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(username='admin').update(role='ADMIN')
    User.objects.filter(is_superuser=True).update(role='ADMIN')


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_provider_to_agent'),
    ]

    operations = [
        migrations.RunPython(set_admin_role, noop),
    ]
