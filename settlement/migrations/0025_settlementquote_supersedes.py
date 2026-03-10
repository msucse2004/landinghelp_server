# 재견적 흐름: 새 견적이 대체한 이전 견적 추적

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0024_human_review_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementquote',
            name='supersedes',
            field=models.ForeignKey(
                blank=True,
                help_text='재제출·재견적 흐름에서 이 견적이 대체한 이전 견적.',
                null=True,
                on_delete=models.SET_NULL,
                related_name='superseded_by_quotes',
                to='settlement.settlementquote',
                verbose_name='대체한 견적',
            ),
        ),
    ]
