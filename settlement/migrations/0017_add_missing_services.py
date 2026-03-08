# 사용자 요청 서비스 목록 중 DB에 없는 항목 추가

from decimal import Decimal
from django.db import migrations


# (code, name, category) — 기존 코드와 겹치지 않는 신규만
NEW_SERVICES = [
    ('RENTAL_CHECK_PAYMENT', '주택/아파트 수표 지불 대납', '주거/임대'),
    ('UTILITY_ACCOUNT_SETUP', '유틸리티 온라인 계정 및 자동이체 설정', '생활편의'),
    ('RENTER_INSURANCE', '임차인 보험 구입', '주거/임대'),
    ('VEHICLE_INSURANCE', '자동차 보험 구입', '교통/차량'),
    ('DMV_WRITTEN_TEST', 'DMV 운전면허 필기 시험 예약/동행', '교통/차량'),
    ('DMV_ROAD_TEST', 'DMV 운전면허 실기 시험 동행', '교통/차량'),
    ('CONSULATE_LICENSE_CERT', '한국면허 영사관 공증서 신청 (GA, TN, AL주)', '행정/문서'),
    ('PUBLIC_SCHOOL_ENROLLMENT', '자녀 공립학교 등록', '의료/교육'),
    ('PRIVATE_SCHOOL_SUPPORT', '자녀 사립학교 조사/지원 및 수속', '의료/교육'),
    ('HEALTH_INSURANCE', '건강 보험 구입', '의료/교육'),
    ('SSN_APPOINTMENT', 'SSN 신청 : 소셜국 예약', '행정/문서'),
    ('SSN_ACCOMPANIMENT', 'SSN 신청 : 소셜국 동행/통역', '행정/문서'),
    ('VEHICLE_RENT_RETURN', '자동차 렌트 반납 동행', '교통/차량'),
    ('AMAZON_PURCHASE', '입국전 필수 물품 아마존 구매 대행', '생활편의'),
    ('LLC_FORMATION', '회사 설립 (LLC)', '행정/문서'),
    ('HOUSE_KEY_PICKUP', '주택/아파트 House Key 픽업', '주거/임대'),
]


def add_services(apps, schema_editor):
    SettlementService = apps.get_model('settlement', 'SettlementService')
    for code, name, category in NEW_SERVICES:
        SettlementService.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'category': category,
                'required_time': 60,
                'customer_price': Decimal('0'),
                'agent_price': Decimal('0'),
                'is_active': True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0016_plan_service_task'),
    ]

    operations = [
        migrations.RunPython(add_services, noop),
    ]
