from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0035_documentsignature'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AvailabilityRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('participant_role', models.CharField(choices=[('CUSTOMER', '고객'), ('AGENT', '에이전트')], db_index=True, max_length=20, verbose_name='응답 대상 역할')),
                ('timezone_name', models.CharField(default='UTC', max_length=64, verbose_name='기준 타임존')),
                ('status', models.CharField(choices=[('OPEN', '요청됨'), ('RESPONDED', '응답 완료'), ('CLOSED', '종료'), ('CANCELED', '취소')], db_index=True, default='OPEN', max_length=20, verbose_name='상태')),
                ('message', models.TextField(blank=True, verbose_name='안내 메시지')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True, verbose_name='종료 시각')),
                ('requested_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requested_availability_requests', to=settings.AUTH_USER_MODEL, verbose_name='요청 생성자')),
                ('schedule_plan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='availability_requests', to='settlement.servicescheduleplan', verbose_name='일정 플랜')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availability_requests', to='survey.surveysubmission', verbose_name='설문 제출')),
                ('target_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availability_requests', to=settings.AUTH_USER_MODEL, verbose_name='응답 대상 사용자')),
            ],
            options={
                'verbose_name': '가용 시간 요청',
                'verbose_name_plural': '가용 시간 요청',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['submission', 'participant_role', 'status'], name='settlement_a_submiss_66680f_idx'), models.Index(fields=['target_user', 'status'], name='settlement_a_target__64d1a2_idx')],
            },
        ),
        migrations.CreateModel(
            name='AvailabilityResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timezone_name', models.CharField(default='UTC', max_length=64, verbose_name='응답 타임존')),
                ('note', models.TextField(blank=True, verbose_name='응답 메모')),
                ('revision', models.PositiveIntegerField(default=1, verbose_name='응답 리비전')),
                ('submitted_at', models.DateTimeField(auto_now_add=True, verbose_name='응답 시각')),
                ('request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='responses', to='settlement.availabilityrequest', verbose_name='가용 시간 요청')),
                ('responded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='availability_responses', to=settings.AUTH_USER_MODEL, verbose_name='응답 사용자')),
            ],
            options={
                'verbose_name': '가용 시간 응답',
                'verbose_name_plural': '가용 시간 응답',
                'ordering': ['-submitted_at'],
                'unique_together': {('request', 'revision')},
            },
        ),
        migrations.CreateModel(
            name='AvailabilitySlot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weekday', models.PositiveSmallIntegerField(choices=[(0, '월요일'), (1, '화요일'), (2, '수요일'), (3, '목요일'), (4, '금요일'), (5, '토요일'), (6, '일요일')], db_index=True, verbose_name='요일')),
                ('start_time', models.TimeField(verbose_name='시작 시간')),
                ('end_time', models.TimeField(verbose_name='종료 시간')),
                ('timezone_name', models.CharField(default='UTC', max_length=64, verbose_name='슬롯 타임존')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('response', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='slots', to='settlement.availabilityresponse', verbose_name='가용 시간 응답')),
            ],
            options={
                'verbose_name': '가용 시간 슬롯',
                'verbose_name_plural': '가용 시간 슬롯',
                'ordering': ['weekday', 'start_time', 'id'],
            },
        ),
    ]
