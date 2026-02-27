from django.core.management.base import BaseCommand
from billing.models import Plan


PLANS = [
    # CUSTOMER (가격: 월 단위, free_agent_service_codes: 무료 Agent 서비스 코드 목록)
    {'code': Plan.Code.C_BASIC, 'target_role': Plan.TargetRole.CUSTOMER, 'tier': Plan.Tier.BASIC, 'features': {'landing_count': 1, 'price_monthly': 0}, 'free_agent_service_codes': []},
    {'code': Plan.Code.C_STANDARD, 'target_role': Plan.TargetRole.CUSTOMER, 'tier': Plan.Tier.STANDARD, 'features': {'landing_count': 5, 'price_monthly': 9900}, 'free_agent_service_codes': ['AIRPORT_PICKUP']},
    {'code': Plan.Code.C_PREMIUM, 'target_role': Plan.TargetRole.CUSTOMER, 'tier': Plan.Tier.PREMIUM, 'features': {'landing_count': 999, 'price_monthly': 29900}, 'free_agent_service_codes': []},
    # AGENT
    {'code': Plan.Code.P_BASIC, 'target_role': Plan.TargetRole.AGENT, 'tier': Plan.Tier.BASIC, 'features': {'clients': 10, 'price_monthly': 0}, 'free_agent_service_codes': []},
    {'code': Plan.Code.P_STANDARD, 'target_role': Plan.TargetRole.AGENT, 'tier': Plan.Tier.STANDARD, 'features': {'clients': 50, 'price_monthly': 19900}, 'free_agent_service_codes': []},
    {'code': Plan.Code.P_PREMIUM, 'target_role': Plan.TargetRole.AGENT, 'tier': Plan.Tier.PREMIUM, 'features': {'clients': 999, 'price_monthly': 49900}, 'free_agent_service_codes': []},
]


class Command(BaseCommand):
    help = '초기 플랜 6개 생성 (C_BASIC~C_PREMIUM, P_BASIC~P_PREMIUM)'

    def handle(self, *args, **options):
        created = 0
        for p in PLANS:
            plan, created_flag = Plan.objects.update_or_create(
                code=p['code'],
                defaults={
                    'target_role': p['target_role'],
                    'tier': p['tier'],
                    'features': p['features'],
                    'free_agent_service_codes': p.get('free_agent_service_codes', []),
                    'is_active': True,
                },
            )
            if created_flag:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'생성: {plan.code}'))
            else:
                self.stdout.write(f'업데이트: {plan.code}')
        self.stdout.write(self.style.SUCCESS(f'완료. 생성 {created}개, 총 {len(PLANS)}개 플랜'))
