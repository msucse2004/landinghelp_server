from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('settlement', '0029_lsa_sourcing_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='LsaAgentResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision', models.CharField(choices=[('ACCEPT_AS_IS', '제안 일정 그대로 수락'), ('PARTIAL', '일부 수락/일부 조정'), ('DECLINE', '전체 거절')], db_index=True, default='ACCEPT_AS_IS', max_length=20, verbose_name='응답 결정')),
                ('note', models.TextField(blank=True, verbose_name='응답 메모')),
                ('revision', models.PositiveIntegerField(default=1, verbose_name='응답 리비전')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='responses', to='settlement.lsaagentrequest', verbose_name='LSA Agent 요청')),
                ('responded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lsa_responses', to=settings.AUTH_USER_MODEL, verbose_name='응답 Agent')),
            ],
            options={
                'verbose_name': 'LSA Agent 응답',
                'verbose_name_plural': 'LSA Agent 응답',
                'ordering': ['-created_at'],
                'unique_together': {('request', 'revision')},
            },
        ),
        migrations.CreateModel(
            name='LsaAgentResponseItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service_code', models.CharField(blank=True, max_length=50, verbose_name='서비스 코드')),
                ('service_label', models.CharField(blank=True, max_length=200, verbose_name='서비스 표시명')),
                ('proposed_starts_at', models.DateTimeField(blank=True, null=True, verbose_name='제안 시작 시각')),
                ('proposed_ends_at', models.DateTimeField(blank=True, null=True, verbose_name='제안 종료 시각')),
                ('action', models.CharField(choices=[('ACCEPT', '수락'), ('SUGGEST_CHANGE', '변경 제안'), ('UNAVAILABLE', '불가')], default='ACCEPT', max_length=20, verbose_name='서비스별 응답')),
                ('suggested_starts_at', models.DateTimeField(blank=True, null=True, verbose_name='제안 변경 시작 시각')),
                ('suggested_ends_at', models.DateTimeField(blank=True, null=True, verbose_name='제안 변경 종료 시각')),
                ('note', models.TextField(blank=True, verbose_name='항목 메모')),
                ('response', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='settlement.lsaagentresponse', verbose_name='LSA 응답')),
            ],
            options={
                'verbose_name': 'LSA Agent 응답 항목',
                'verbose_name_plural': 'LSA Agent 응답 항목',
                'ordering': ['id'],
            },
        ),
    ]
