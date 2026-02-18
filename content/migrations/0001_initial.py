# Generated manually for initial schema

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Content',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('body', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_contents', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '컨텐츠',
                'verbose_name_plural': '컨텐츠',
            },
        ),
        migrations.CreateModel(
            name='ContentPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('can_view', models.BooleanField(default=True)),
                ('can_edit', models.BooleanField(default=False)),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permissions', to='content.content')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_permissions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '컨텐츠 권한',
                'verbose_name_plural': '컨텐츠 권한',
            },
        ),
        migrations.AddConstraint(
            model_name='contentpermission',
            constraint=models.UniqueConstraint(fields=('content', 'user'), name='unique_content_user'),
        ),
    ]
