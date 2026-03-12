# Generated migration file

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0025_settlementquote_supersedes'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='agentappointmentrequest',
            options={'ordering': ['-created_at'], 'verbose_name': '약속 신청', 'verbose_name_plural': '약속 신청'},
        ),
        migrations.AlterModelOptions(
            name='settlementquoterequest',
            options={'ordering': ['-created_at'], 'verbose_name': '견적 요청', 'verbose_name_plural': '견적 요청'},
        ),
        migrations.AlterModelOptions(
            name='settlementservice',
            options={'ordering': ['code'], 'verbose_name': '정산 서비스', 'verbose_name_plural': '정산 서비스'},
        ),
        migrations.AlterModelOptions(
            name='usersettlementplan',
            options={'ordering': ['-created_at'], 'verbose_name': '사용자 정산 계획', 'verbose_name_plural': '사용자 정산 계획'},
        ),
    ]
