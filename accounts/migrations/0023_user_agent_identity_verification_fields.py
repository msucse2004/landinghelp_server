from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_expand_user_roles_and_backfill_staff_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='agent_identity_verification_status',
            field=models.CharField(
                choices=[
                    ('NOT_REQUIRED', '확인 불필요'),
                    ('REQUIRED', '신분 확인 서류 필요'),
                    ('SUBMITTED', '신분 확인 서류 제출됨'),
                    ('VERIFIED', '신분 확인 완료'),
                ],
                db_index=True,
                default='NOT_REQUIRED',
                help_text='최초 온보딩 시 신분증 확인이 필요한 Agent 여부와 처리 상태',
                max_length=20,
                verbose_name='Agent 신분 확인 상태',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='agent_identity_verified_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Agent 신분 확인 완료 시각'),
        ),
    ]