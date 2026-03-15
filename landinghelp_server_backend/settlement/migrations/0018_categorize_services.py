# 서비스 코드별 카테고리 통일 (주거/임대, 교통/차량, 생활편의, 의료/교육, 행정/문서, 기타)

from django.db import migrations

# code -> category (SettlementService.Category 값)
CODE_TO_CATEGORY = {
    # 주거/임대
    'HOUSING_TOUR': '주거/임대',
    'RENTAL_SUPPORT': '주거/임대',
    'RENTAL_APPROVAL': '주거/임대',
    'RENTAL_CONTRACT': '주거/임대',
    'HOUSING_RESEARCH': '주거/임대',
    'HOUSING_VIDEO': '주거/임대',
    'RENTAL_CHECK_PAYMENT': '주거/임대',
    'RENTER_INSURANCE': '주거/임대',
    'HOUSE_KEY_PICKUP': '주거/임대',
    # 교통/차량
    'AIRPORT_PICKUP': '교통/차량',
    'DRIVERS_LICENSE': '교통/차량',
    'VEHICLE_PURCHASE': '교통/차량',
    'VEHICLE_REGISTRATION': '교통/차량',
    'VEHICLE_RENT': '교통/차량',
    'VEHICLE_INSURANCE': '교통/차량',
    'DMV_WRITTEN_TEST': '교통/차량',
    'DMV_ROAD_TEST': '교통/차량',
    'VEHICLE_RENT_RETURN': '교통/차량',
    # 생활편의
    'PHONE_SETUP': '생활편의',
    'UTILITY_SETUP': '생활편의',
    'UTILITY_ACCOUNT_SETUP': '생활편의',
    'AMAZON_PURCHASE': '생활편의',
    # 의료/교육
    'HOSPITAL_VISIT': '의료/교육',
    'SCHOOL_VISIT': '의료/교육',
    'PUBLIC_SCHOOL_ENROLLMENT': '의료/교육',
    'PRIVATE_SCHOOL_SUPPORT': '의료/교육',
    'HEALTH_INSURANCE': '의료/교육',
    # 행정/문서
    'BANK_ACCOUNT': '행정/문서',
    'SSN_APPLICATION': '행정/문서',
    'SSN_APPOINTMENT': '행정/문서',
    'SSN_ACCOMPANIMENT': '행정/문서',
    'CONSULATE_LICENSE_CERT': '행정/문서',
    'LLC_FORMATION': '행정/문서',
    # 기타
    'AREA_TOUR': '기타',
}


def apply_categories(apps, schema_editor):
    SettlementService = apps.get_model('settlement', 'SettlementService')
    for code, category in CODE_TO_CATEGORY.items():
        SettlementService.objects.filter(code=code).update(category=category)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0017_add_missing_services'),
    ]

    operations = [
        migrations.RunPython(apply_categories, noop),
    ]
