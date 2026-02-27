# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_add_agent_cities'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agent_states',
            field=models.JSONField(blank=True, default=list, help_text='에이전트가 커버하는 주 코드 목록 (예: NC, CA, TX)', verbose_name='커버 주(State)'),
        ),
    ]
