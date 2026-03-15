# AI agent: AssistantKnowledge + AssistantInteractionLog

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('messaging', '0005_conversation_survey_submission'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AssistantKnowledge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200, verbose_name='제목')),
                ('content', models.TextField(help_text='어시스턴트가 참고할 텍스트.', verbose_name='내용')),
                ('category', models.CharField(choices=[('FAQ', 'FAQ'), ('SERVICE_INSTRUCTION', '서비스 안내'), ('INTERNAL_NOTE', '내부 메모')], db_index=True, default='FAQ', max_length=30, verbose_name='분류')),
                ('service_code', models.CharField(blank=True, db_index=True, help_text='특정 서비스에만 적용할 때 코드 입력. 비우면 전체.', max_length=50, verbose_name='서비스 코드')),
                ('is_active', models.BooleanField(default=True, verbose_name='활성')),
                ('display_order', models.PositiveIntegerField(default=0, verbose_name='표시 순서')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': '어시스턴트 지식',
                'verbose_name_plural': '어시스턴트 지식',
                'ordering': ['display_order', 'id'],
            },
        ),
        migrations.CreateModel(
            name='AssistantInteractionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(max_length=20)),
                ('input_text', models.TextField(blank=True, verbose_name='입력(사용자 메시지 또는 컨텍스트 요약)')),
                ('output_text', models.TextField(blank=True, verbose_name='출력(어시스턴트 응답)')),
                ('model_used', models.CharField(blank=True, max_length=100, verbose_name='사용 모델')),
                ('uncertainty_flagged', models.BooleanField(default=False, verbose_name='불확실성 플래그')),
                ('meta', models.JSONField(blank=True, default=dict, verbose_name='메타')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='assistant_logs', to='messaging.conversation', verbose_name='대화')),
                ('message', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assistant_logs', to='messaging.message', verbose_name='응답 메시지')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assistant_interaction_logs', to=settings.AUTH_USER_MODEL, verbose_name='사용자')),
            ],
            options={
                'verbose_name': '어시스턴트 상호작용 로그',
                'verbose_name_plural': '어시스턴트 상호작용 로그',
                'ordering': ['-created_at'],
            },
        ),
    ]
