# Migration: Plan (code, target_role, tier, features) / Subscription (status, current_period_end)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_plan_schema(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    codes = ['C_BASIC', 'C_STANDARD', 'C_PREMIUM', 'P_BASIC', 'P_STANDARD', 'P_PREMIUM']
    for i, plan in enumerate(Plan.objects.order_by('id')):
        code = codes[min(i, 5)]
        plan.code = code
        plan.target_role = 'PROVIDER' if i >= 3 else 'CUSTOMER'
        plan.tier = (i % 3) + 1
        plan.features = {}
        plan.save()


def migrate_subscription_schema(apps, schema_editor):
    Subscription = apps.get_model('billing', 'Subscription')
    Subscription.objects.all().update(status='ACTIVE')


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Plan: add new fields
        migrations.AddField(
            model_name='plan',
            name='code',
            field=models.CharField(max_length=30, null=True),
        ),
        migrations.AddField(
            model_name='plan',
            name='target_role',
            field=models.CharField(max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='plan',
            name='tier',
            field=models.PositiveSmallIntegerField(null=True),
        ),
        migrations.AddField(
            model_name='plan',
            name='features',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(migrate_plan_schema, migrations.RunPython.noop),
        migrations.RemoveField(model_name='plan', name='name'),
        migrations.RemoveField(model_name='plan', name='price'),
        migrations.AlterField(
            model_name='plan',
            name='code',
            field=models.CharField(max_length=30, unique=True),
        ),
        migrations.AlterField(
            model_name='plan',
            name='target_role',
            field=models.CharField(
                choices=[('CUSTOMER', '고객'), ('PROVIDER', '제공자')],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='plan',
            name='tier',
            field=models.PositiveSmallIntegerField(
                choices=[(1, '베이직'), (2, '스탠다드'), (3, '프리미엄')],
            ),
        ),
        # Subscription: add status, current_period_end; remove expires_at, is_active
        migrations.AddField(
            model_name='subscription',
            name='status',
            field=models.CharField(
                choices=[('ACTIVE', '활성'), ('CANCELED', '취소됨'), ('PAST_DUE', '결제연체')],
                default='ACTIVE',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='subscription',
            name='current_period_end',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(migrate_subscription_schema, migrations.RunPython.noop),
        migrations.RemoveField(model_name='subscription', name='expires_at'),
        migrations.RemoveField(model_name='subscription', name='is_active'),
    ]
