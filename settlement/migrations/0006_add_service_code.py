# Add code field to SettlementService, backfill from name mapping

from django.db import migrations, models

# name -> code (from constants)
NAME_TO_CODE = {
    '주택투어': 'HOUSING_TOUR',
    '임대지원': 'RENTAL_SUPPORT',
    '임대승인 코디네이션': 'RENTAL_APPROVAL',
    '임대계약': 'RENTAL_CONTRACT',
    '조택조사': 'HOUSING_RESEARCH',
    '주택 영상촬영': 'HOUSING_VIDEO',
    '운전면허시험': 'DRIVERS_LICENSE',
    '차량구매': 'VEHICLE_PURCHASE',
    '차량등록': 'VEHICLE_REGISTRATION',
    '차량렌트': 'VEHICLE_RENT',
    '공항픽업': 'AIRPORT_PICKUP',
    '전화개통/배송': 'PHONE_SETUP',
    '이틸리티 개통': 'UTILITY_SETUP',
    '병원방문': 'HOSPITAL_VISIT',
    '자녀학교 방문': 'SCHOOL_VISIT',
    '은행계좌 개설': 'BANK_ACCOUNT',
    '소셜번호 신청': 'SSN_APPLICATION',
    '지역투어': 'AREA_TOUR',
}


def backfill_codes(apps, schema_editor):
    SettlementService = apps.get_model('settlement', 'SettlementService')
    for svc in SettlementService.objects.all():
        if not svc.code and svc.name in NAME_TO_CODE:
            svc.code = NAME_TO_CODE[svc.name]
            svc.save()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0005_remove_ordering_from_service'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementservice',
            name='code',
            field=models.CharField(blank=True, help_text='견적/스케줄 식별용 (예: DRIVERS_LICENSE). 비어있으면 id 사용', max_length=50, null=True, unique=True, verbose_name='서비스 코드'),
        ),
        migrations.RunPython(backfill_codes, noop),
    ]
