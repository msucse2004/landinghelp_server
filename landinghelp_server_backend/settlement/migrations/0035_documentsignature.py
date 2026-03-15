from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0034_case_document'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DocumentSignature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('signer_role', models.CharField(choices=[('CUSTOMER', '고객'), ('INTERNAL', '내부 담당자'), ('AGENT', '에이전트'), ('THIRD_PARTY', '외부 서명자')], db_index=True, max_length=20, verbose_name='서명자 역할')),
                ('signed_at', models.DateTimeField(db_index=True, verbose_name='서명 시각')),
                ('signature_type', models.CharField(choices=[('INTERNAL_TRANSITION', '내부 상태 전이 서명'), ('CLICK_TO_SIGN', '클릭 서명'), ('PROVIDER_WEBHOOK', '전자서명 제공자 Webhook')], default='INTERNAL_TRANSITION', max_length=30, verbose_name='서명 유형')),
                ('audit_payload', models.JSONField(blank=True, default=dict, verbose_name='감사 페이로드')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP 주소')),
                ('user_agent', models.TextField(blank=True, verbose_name='User Agent')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('document', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='signatures', to='settlement.casedocument', verbose_name='문서')),
                ('signer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='document_signatures', to=settings.AUTH_USER_MODEL, verbose_name='서명자')),
            ],
            options={
                'verbose_name': '문서 서명',
                'verbose_name_plural': '문서 서명',
                'ordering': ['-signed_at', '-id'],
                'indexes': [models.Index(fields=['document', 'signer_role'], name='settlement_d_documen_62001b_idx'), models.Index(fields=['signer', 'signed_at'], name='settlement_d_signer__f92bdb_idx')],
            },
        ),
    ]
