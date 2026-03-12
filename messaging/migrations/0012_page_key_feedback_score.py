from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0011_customer_request_learning_summary'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageKeyFeedbackScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_key', models.CharField(db_index=True, max_length=128, unique=True, verbose_name='페이지 키')),
                ('thumbs_up_count', models.PositiveIntegerField(default=0, verbose_name='👍 수')),
                ('thumbs_down_count', models.PositiveIntegerField(default=0, verbose_name='👎 수')),
                ('positive_label_count', models.PositiveIntegerField(default=0, help_text='edit_saved success 기반 strong/medium label', verbose_name='positive 라벨 수')),
                ('negative_label_count', models.PositiveIntegerField(default=0, help_text='used_other_page 기반 negative label', verbose_name='negative 라벨 수')),
                ('total_seen', models.PositiveIntegerField(default=0, help_text='이 page_key 가 predicted_primary_page 로 선택된 총 회수', verbose_name='예측 총 회수')),
                ('score_boost', models.FloatField(default=0.0, help_text='[-1, 1] 범위. 집계 데이터 부족 시 신뢰도 감쇠 적용.', verbose_name='점수 보정값')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '페이지 키 피드백 점수',
                'verbose_name_plural': '페이지 키 피드백 점수',
                'ordering': ['-score_boost'],
            },
        ),
    ]
