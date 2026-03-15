# Generated manually - 정착 플랜 18개 서비스 항목 시드

import random
from django.db import migrations


SERVICES = [
    ('주택투어', '주거/임대'),
    ('임대지원', '주거/임대'),
    ('임대승인 코디네이션', '주거/임대'),
    ('임대계약', '주거/임대'),
    ('조택조사', '주거/임대'),
    ('주택 영상촬영', '주거/임대'),
    ('운전면허시험', '교통/차량'),
    ('차량구매', '교통/차량'),
    ('차량등록', '교통/차량'),
    ('차량렌트', '교통/차량'),
    ('공항픽업', '교통/차량'),
    ('전화개통/배송', '생활편의'),
    ('이틸리티 개통', '생활편의'),
    ('병원방문', '의료/교육'),
    ('자녀학교 방문', '의료/교육'),
    ('은행계좌 개설', '행정/문서'),
    ('소셜번호 신청', '행정/문서'),
    ('지역투어', '기타'),
]


def seed_services(apps, schema_editor):
    SettlementService = apps.get_model('settlement', 'SettlementService')
    random.seed(42)
    for i, (name, category) in enumerate(SERVICES):
        SettlementService.objects.get_or_create(
            name=name,
            category=category,
            defaults={
                'required_time': random.randint(30, 180),
                'customer_price': random.randint(5000, 80000),
                'agent_price': random.randint(3000, 50000),
                'is_active': True,
            },
        )


def reverse_seed(apps, schema_editor):
    SettlementService = apps.get_model('settlement', 'SettlementService')
    names = [s[0] for s in SERVICES]
    SettlementService.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('settlement', '0003_add_settlement_service'),
    ]

    operations = [
        migrations.RunPython(seed_services, reverse_seed),
    ]
