# Generated migration: role ADMIN/PROVIDER/CUSTOMER, status ACTIVE/PENDING/SUSPENDED

from django.db import migrations, models


def migrate_roles(apps, schema_editor):
    """기존 role 값을 새 규격으로 변환"""
    User = apps.get_model('accounts', 'User')
    mapping = {'admin': 'ADMIN', 'member': 'PROVIDER', 'guest': 'CUSTOMER'}
    for user in User.objects.all():
        user.role = mapping.get(user.role, 'CUSTOMER')
        user.save(update_fields=['role'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='status',
            field=models.CharField(
                choices=[('ACTIVE', '활성'), ('PENDING', '대기'), ('SUSPENDED', '정지')],
                default='ACTIVE',
                max_length=20,
            ),
        ),
        migrations.RunPython(migrate_roles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('ADMIN', '관리자'), ('PROVIDER', '제공자'), ('CUSTOMER', '고객')],
                default='CUSTOMER',
                max_length=20,
            ),
        ),
    ]
