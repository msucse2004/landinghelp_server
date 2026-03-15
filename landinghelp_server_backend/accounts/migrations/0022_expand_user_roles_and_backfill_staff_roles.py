from django.db import migrations, models


def forward_map_roles(apps, schema_editor):
    User = apps.get_model('accounts', 'User')

    User.objects.filter(is_superuser=True).update(role='SUPER_ADMIN')
    User.objects.filter(is_superuser=False, is_staff=True).exclude(role__in=['AGENT', 'CUSTOMER']).update(role='ADMIN')


def reverse_map_roles(apps, schema_editor):
    User = apps.get_model('accounts', 'User')

    User.objects.filter(role='SUPER_ADMIN').update(role='ADMIN')
    User.objects.filter(role__in=['SUPERVISOR', 'HQ_STAFF']).update(role='ADMIN')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_agent_level_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('SUPER_ADMIN', '슈퍼 관리자'),
                    ('ADMIN', '관리자'),
                    ('SUPERVISOR', '운영 관리자'),
                    ('HQ_STAFF', '본사 스태프'),
                    ('CUSTOMER', '고객'),
                    ('AGENT', '에이전트'),
                ],
                default='CUSTOMER',
                max_length=20,
            ),
        ),
        migrations.RunPython(forward_map_roles, reverse_map_roles),
    ]
