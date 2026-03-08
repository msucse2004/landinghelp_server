# 서비스별 State별 가격을 100~300 USD 사이 랜덤으로 DB에 넣습니다.

import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from settlement.models import SettlementService, ServiceStatePrice
from settlement.forms import US_STATES


# US_STATES 첫 항목은 ('', '선택하세요') 이므로 제외
STATE_CODES = [code for code, _ in US_STATES if code]


class Command(BaseCommand):
    help = '서비스별 State별 가격을 100~300 USD 랜덤으로 시드합니다. (기존 행은 업데이트)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--update',
            action='store_true',
            help='이미 있는 ServiceStatePrice도 가격을 랜덤으로 갱신합니다.',
        )

    def handle(self, *args, **options):
        do_update = options.get('update', False)
        services = list(SettlementService.objects.filter(is_active=True).order_by('id'))
        if not services:
            self.stdout.write(self.style.WARNING('활성 서비스가 없습니다.'))
            return
        created = 0
        updated = 0
        for service in services:
            for state_code in STATE_CODES:
                customer_price = Decimal(str(random.randint(100, 300)))
                agent_price = Decimal(str(random.randint(100, 300)))
                obj, was_created = ServiceStatePrice.objects.get_or_create(
                    service=service,
                    state_code=state_code,
                    defaults={
                        'customer_price': customer_price,
                        'agent_price': agent_price,
                    },
                )
                if was_created:
                    created += 1
                elif do_update:
                    obj.customer_price = customer_price
                    obj.agent_price = agent_price
                    obj.save()
                    updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f'ServiceStatePrice: 생성 {created}건' + (f', 갱신 {updated}건' if updated else '') + '.'
            )
        )
