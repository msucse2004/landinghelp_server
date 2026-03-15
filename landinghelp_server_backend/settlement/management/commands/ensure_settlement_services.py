# 정착 서비스 항목이 DB에 모두 있는지 확인하고, 없으면 생성합니다.
# 마이그레이션 0017이 적용되지 않은 환경에서 18개만 보일 때 이 명령으로 34개로 맞출 수 있습니다.

from decimal import Decimal
from django.core.management.base import BaseCommand
from settlement.models import SettlementService


# (code, name, category) — 18개(기존 시드) + 16개(0017 추가분) = 34개
FULL_SERVICES = [
    # 기존 18 (0004 + 0006 코드 매핑)
    ('HOUSING_TOUR', '주택투어', '주거/임대'),
    ('RENTAL_SUPPORT', '임대지원', '주거/임대'),
    ('RENTAL_APPROVAL', '임대승인 코디네이션', '주거/임대'),
    ('RENTAL_CONTRACT', '임대계약', '주거/임대'),
    ('HOUSING_RESEARCH', '조택조사', '주거/임대'),
    ('HOUSING_VIDEO', '주택 영상촬영', '주거/임대'),
    ('DRIVERS_LICENSE', '운전면허시험', '교통/차량'),
    ('VEHICLE_PURCHASE', '차량구매', '교통/차량'),
    ('VEHICLE_REGISTRATION', '차량등록', '교통/차량'),
    ('VEHICLE_RENT', '차량렌트', '교통/차량'),
    ('AIRPORT_PICKUP', '공항픽업', '교통/차량'),
    ('PHONE_SETUP', '전화개통/배송', '생활편의'),
    ('UTILITY_SETUP', '이틸리티 개통', '생활편의'),
    ('HOSPITAL_VISIT', '병원방문', '의료/교육'),
    ('SCHOOL_VISIT', '자녀학교 방문', '의료/교육'),
    ('BANK_ACCOUNT', '은행계좌 개설', '행정/문서'),
    ('SSN_APPLICATION', '소셜번호 신청', '행정/문서'),
    ('AREA_TOUR', '지역투어', '기타'),
    # 0017에서 추가된 16개
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


class Command(BaseCommand):
    help = 'SettlementService 항목이 34개 모두 있는지 확인하고, 없으면 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='생성될 항목만 출력하고 DB에는 쓰지 않습니다.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        created = 0
        for code, name, category in FULL_SERVICES:
            if dry_run:
                exists = SettlementService.objects.filter(code=code).exists()
                if not exists:
                    self.stdout.write(self.style.WARNING(f'추가될 항목: {code} - {name}'))
                    created += 1
                continue
            obj, was_created = SettlementService.objects.get_or_create(
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
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'생성: {obj.code} - {obj.name}'))

        total = SettlementService.objects.count()
        if dry_run:
            self.stdout.write(self.style.NOTICE(f'[dry-run] 추가될 개수: {created} (현재: {total}, 목표: {len(FULL_SERVICES)})'))
        else:
            self.stdout.write(self.style.SUCCESS(f'완료. 새로 생성: {created}, 전체 서비스 수: {total} (목표: {len(FULL_SERVICES)})'))
