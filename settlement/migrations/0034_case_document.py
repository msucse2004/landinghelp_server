from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0016_conversation_workspace_type'),
        ('settlement', '0033_schedule_item_recommendation_metadata_json'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='CaseDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('QUOTE', '견적서'), ('INVOICE', '인보이스'), ('CONSENT_FORM', '동의서'), ('POWER_OF_ATTORNEY', '위임장'), ('LSA_FORM', 'LSA 서류'), ('SERVICE_COMPLETION_FORM', '서비스 완료 확인서'), ('REAL_ESTATE_CONTRACT', '부동산 계약서'), ('UTILITY_CONFIRMATION', '공과금 확인서'), ('CUSTOMER_REQUESTED_DOCUMENT', '고객 요청 문서'), ('CUSTOMER_UPLOADED_DOCUMENT', '고객 업로드 문서'), ('SIGNED_FINAL_PACKAGE', '최종 서명 패키지'), ('AGENT_ID_FRONT', 'Agent 신분증 앞면'), ('AGENT_ID_BACK', 'Agent 신분증 뒷면')], db_index=True, max_length=40, verbose_name='문서 유형')),
                ('document_scope', models.CharField(choices=[('CASE', '케이스 전체'), ('CONVERSATION', '대화 단위'), ('SERVICE_EXECUTION', '서비스 수행 단위')], db_index=True, default='CASE', max_length=30, verbose_name='문서 범위')),
                ('visibility_level', models.CharField(choices=[('PRIVATE_CUSTOMER', '고객 민감(제한 공개)'), ('PRIVATE_FINANCIAL', '재무 민감(제한 공개)'), ('INTERNAL_GENERAL', '내부 일반'), ('LOCAL_EXECUTION', '현지진행 공유'), ('SHARED_WITH_CUSTOMER', '고객 공유')], db_index=True, default='SHARED_WITH_CUSTOMER', max_length=40, verbose_name='가시성 레벨')),
                ('file', models.FileField(upload_to='settlement/case_documents/%Y/%m/%d/', verbose_name='문서 파일')),
                ('original_filename', models.CharField(blank=True, max_length=255, verbose_name='원본 파일명')),
                ('status', models.CharField(choices=[('DRAFT', '초안'), ('UPLOADED', '업로드됨'), ('GENERATED', '자동 생성됨'), ('ARCHIVED', '보관')], db_index=True, default='UPLOADED', max_length=20, verbose_name='상태')),
                ('version', models.PositiveIntegerField(default=1, verbose_name='버전')),
                ('metadata', models.JSONField(blank=True, default=dict, verbose_name='메타데이터')),
                ('is_signed_final', models.BooleanField(default=False, verbose_name='최종 서명 완료')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('conversation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='case_documents', to='messaging.conversation', verbose_name='연결 대화')),
                ('owner_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_case_documents', to=settings.AUTH_USER_MODEL, verbose_name='문서 소유 사용자')),
                ('replaces', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replaced_by_documents', to='settlement.casedocument', verbose_name='대체하는 이전 문서')),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='case_documents', to='survey.surveysubmission', verbose_name='설문 제출')),
                ('uploaded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='uploaded_case_documents', to=settings.AUTH_USER_MODEL, verbose_name='업로드 사용자')),
            ],
            options={
                'verbose_name': '케이스 문서',
                'verbose_name_plural': '케이스 문서',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='casedocument',
            index=models.Index(fields=['submission', 'document_type'], name='settlement_c_submiss_983819_idx'),
        ),
        migrations.AddIndex(
            model_name='casedocument',
            index=models.Index(fields=['submission', 'visibility_level'], name='settlement_c_submiss_4720ea_idx'),
        ),
    ]
