# Generated manually

from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_add_profile_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.PositiveSmallIntegerField(help_text='1~5점', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)], verbose_name='별점')),
                ('comment', models.TextField(blank=True, verbose_name='한줄평')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings_received', to=settings.AUTH_USER_MODEL, verbose_name='평가 대상 (Agent)')),
                ('rater', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings_given', to=settings.AUTH_USER_MODEL, verbose_name='평가자 (Customer)')),
            ],
            options={
                'verbose_name': '에이전트 별점',
                'verbose_name_plural': '에이전트 별점',
                'ordering': ('-created_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='agentrating',
            constraint=models.UniqueConstraint(fields=('rater', 'agent'), name='unique_agent_rating_per_customer'),
        ),
    ]
