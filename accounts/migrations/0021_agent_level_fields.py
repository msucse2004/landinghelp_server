from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_add_phone_to_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agent_completed_service_count',
            field=models.PositiveIntegerField(default=0, help_text='레벨 계산 시점 기준 완료 서비스 건수', verbose_name='완료 서비스 건수(스냅샷)'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_level',
            field=models.CharField(choices=[('BRONZE', 'Bronze'), ('SILVER', 'Silver'), ('GOLD', 'Gold'), ('DIAMOND', 'Diamond'), ('PLATINUM', 'Platinum')], db_index=True, default='BRONZE', help_text='Bronze/Silver/Gold/Diamond/Platinum 레벨', max_length=20, verbose_name='Agent 레벨'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_level_constraints',
            field=models.JSONField(blank=True, default=dict, help_text='향후 레벨별 제약 룰을 저장하기 위한 구조화 필드', verbose_name='레벨 기반 제약(초안)'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_level_last_evaluated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='레벨 평가 시각'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_level_score',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='완료건수/별점/수락률 기반 계산 점수(0~100 권장)', max_digits=6, null=True, verbose_name='Agent 레벨 점수'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_rating_avg_snapshot',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='레벨 계산 시점 기준 평균 별점(1~5)', max_digits=4, null=True, verbose_name='평점 평균(스냅샷)'),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_accept_rate_snapshot',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='레벨 계산 시점 기준 수락률(0~1 권장)', max_digits=5, null=True, verbose_name='수락률(스냅샷)'),
        ),
    ]
