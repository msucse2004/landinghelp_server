from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0013_manual_confirmed_labels'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerRequestManualLabelRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_id', models.CharField(db_index=True, max_length=64, verbose_name='요청 흐름 ID')),
                ('before_intent', models.CharField(blank=True, max_length=60, verbose_name='수정 전 확정 의도')),
                ('after_intent', models.CharField(blank=True, max_length=60, verbose_name='수정 후 확정 의도')),
                ('before_page_key', models.CharField(blank=True, max_length=128, verbose_name='수정 전 확정 페이지 키')),
                ('after_page_key', models.CharField(blank=True, max_length=128, verbose_name='수정 후 확정 페이지 키')),
                ('before_notes', models.TextField(blank=True, verbose_name='수정 전 메모')),
                ('after_notes', models.TextField(blank=True, verbose_name='수정 후 메모')),
                ('changed_at', models.DateTimeField(auto_now_add=True, verbose_name='변경 시각')),
                ('changed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_label_revision_events', to=settings.AUTH_USER_MODEL, verbose_name='변경한 관리자')),
                ('learning_summary', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='manual_label_revisions', to='messaging.customerrequestlearningsummary', verbose_name='학습 요약')),
            ],
            options={
                'verbose_name': '수동 라벨 변경 이력',
                'verbose_name_plural': '수동 라벨 변경 이력',
                'ordering': ['-changed_at'],
            },
        ),
        migrations.AddIndex(
            model_name='customerrequestmanuallabelrevision',
            index=models.Index(fields=['request_id', '-changed_at'], name='messaging_c_request_e91f7b_idx'),
        ),
        migrations.AddIndex(
            model_name='customerrequestmanuallabelrevision',
            index=models.Index(fields=['learning_summary', '-changed_at'], name='messaging_c_learnin_6c715c_idx'),
        ),
    ]
