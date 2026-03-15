# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_add_agent_states'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agent_cities_by_state',
            field=models.JSONField(blank=True, default=dict, help_text='주별 도시 ID: {"NC": [1,2,3], "CA": [10,11]}', verbose_name='커버 도시 (주별)'),
        ),
    ]
