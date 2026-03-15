# Migration: Content 옵션 A (allowed_roles + min_tier), ContentPermission 제거
# RunSQL로 unique 제약 추가 (Django AlterField slug 시 PostgreSQL _like 인덱스 버그 회피)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_content(apps, schema_editor):
    Content = apps.get_model('content', 'Content')
    for c in Content.objects.order_by('id'):
        base = (c.title[:50] or 'content').replace(' ', '-').lower()
        base = ''.join(x for x in base if x.isalnum() or x == '-') or 'content'
        c.slug = f"{base}-{c.id}"
        c.category = ''
        c.summary = ''
        c.status = 'PUBLISHED'
        c.allowed_roles = ['ADMIN', 'PROVIDER', 'CUSTOMER']
        c.min_tier = 1
        c.is_public = False
        c.save()


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(model_name='contentpermission', name='content'),
        migrations.RemoveField(model_name='contentpermission', name='user'),
        migrations.DeleteModel(name='ContentPermission'),
        migrations.AddField(
            model_name='content',
            name='slug',
            field=models.SlugField(allow_unicode=True, max_length=220, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='content',
            name='category',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='content',
            name='summary',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='content',
            name='status',
            field=models.CharField(
                choices=[('DRAFT', '초안'), ('PUBLISHED', '발행')],
                default='DRAFT',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='content',
            name='allowed_roles',
            field=models.JSONField(blank=True, default=list, help_text='접근 허용 역할 목록'),
        ),
        migrations.AddField(
            model_name='content',
            name='min_tier',
            field=models.PositiveSmallIntegerField(
                choices=[(1, '베이직'), (2, '스탠다드'), (3, '프리미엄')],
                default=1,
            ),
        ),
        migrations.AddField(
            model_name='content',
            name='is_public',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(migrate_content, migrations.RunPython.noop),
        migrations.RunSQL(
            sql=[
                "ALTER TABLE content_content ALTER COLUMN slug SET NOT NULL",
                "CREATE UNIQUE INDEX content_content_slug_uniq ON content_content (slug)",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS content_content_slug_uniq",
                "ALTER TABLE content_content ALTER COLUMN slug DROP NOT NULL",
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='content',
                    name='slug',
                    field=models.SlugField(allow_unicode=True, max_length=220, unique=True),
                ),
            ],
            database_operations=[],
        ),
    ]

