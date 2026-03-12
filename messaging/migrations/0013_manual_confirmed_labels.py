from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0012_page_key_feedback_score'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='customerrequestlearningsummary',
            name='manual_confirmed_intent',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='관리자가 수동으로 확정한 intent. 비어 있으면 자동 라벨 사용.',
                max_length=60,
                verbose_name='관리자 확정 의도',
            ),
        ),
        migrations.AddField(
            model_name='customerrequestlearningsummary',
            name='manual_confirmed_page_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='관리자가 수동으로 확정한 정답 페이지 키. 비어 있으면 자동 라벨 사용.',
                max_length=128,
                verbose_name='관리자 확정 페이지 키',
            ),
        ),
        migrations.AddField(
            model_name='customerrequestlearningsummary',
            name='manual_label_notes',
            field=models.TextField(
                blank=True,
                help_text='수동 확정 사유/메모.',
                verbose_name='수동 라벨 메모',
            ),
        ),
        migrations.AddField(
            model_name='customerrequestlearningsummary',
            name='manual_labeled_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='수동 라벨 시각',
            ),
        ),
        migrations.AddField(
            model_name='customerrequestlearningsummary',
            name='manual_labeled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='manual_labeled_learning_summaries',
                to=settings.AUTH_USER_MODEL,
                verbose_name='수동 라벨 담당자',
            ),
        ),
    ]
