# 설문 재개 시 기존 FINAL_SENT 견적 비활성(결제 대상 제외)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0021_quote_change_request_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementquote',
            name='revision_superseded_at',
            field=models.DateTimeField(
                blank=True,
                help_text='설문 재개 승인 시 설정. 이 견적은 결제 대상에서 제외.',
                null=True,
                verbose_name='수정 요청으로 대체 시각',
            ),
        ),
    ]
