"""
주/도시별로 에이전트 계정을 랜덤 생성.
각 도시당 1명씩 에이전트를 생성하여 모든 도시가 한 명씩 지원되도록 함.

실행: python manage.py create_support_agents
"""
import random
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from community.models import Area
from settlement.models import SettlementService


# 랜덤 이름 풀
FIRST_NAMES = [
    'James', 'John', 'Robert', 'Michael', 'William', 'David', 'Joseph', 'Daniel',
    'Emma', 'Olivia', 'Ava', 'Sophia', 'Isabella', 'Mia', 'Charlotte', 'Amelia',
    '민준', '서준', '도윤', '예준', '시우', '하준', '지호', '주원',
    '서연', '서윤', '지우', '하윤', '하은', '민서', '지유', '수아',
]


def random_birth_date():
    """1980~2000 사이 랜덤 생년월일"""
    year = random.randint(1980, 2000)
    month = random.randint(1, 12)
    day = random.randint(1, 28)  # 28로 제한하여 유효한 날짜 보장
    return date(year, month, day)


def random_name():
    return random.choice(FIRST_NAMES)


def random_gender():
    return random.choice([User.Gender.M, User.Gender.F])


def make_unique_username(base):
    """중복 시 숫자 접미사 추가"""
    username = base
    suffix = 0
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}_{suffix}"
    return username


def make_unique_email(base_email):
    """이메일 중복 시 숫자 접미사 추가"""
    email = base_email
    suffix = 0
    while User.objects.filter(email=email).exists():
        suffix += 1
        local, domain = base_email.rsplit('@', 1)
        email = f"{local}+{suffix}@{domain}"
    return email


class Command(BaseCommand):
    help = "주/도시별로 에이전트 계정 랜덤 생성 (각 도시당 1명, 서비스 전선택, 비밀번호 1234)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 생성 없이 대상 도시/서비스 수만 출력',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        areas = list(Area.objects.order_by('region', 'state_code', 'order', 'id'))
        services = list(SettlementService.objects.filter(is_active=True).values_list('id', flat=True))

        if not areas:
            self.stdout.write(self.style.WARNING("등록된 도시가 없습니다."))
            return
        if not services:
            self.stdout.write(self.style.WARNING("등록된 활성 서비스가 없습니다."))
            return

        self.stdout.write(f"도시 수: {len(areas)}, 서비스 수: {len(services)}")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"[Dry Run] {len(areas)}개 계정 생성 예정"))
            return

        created = 0
        with transaction.atomic():
            for i, area in enumerate(areas):
                # username: 도시 slug 기반, 중복 방지
                base_username = f"agent_{area.slug.replace('-', '_')}"
                username = make_unique_username(base_username)
                email = make_unique_email(f"agent_support_{i+1}@landinghelp.local")

                user = User(
                    username=username,
                    email=email,
                    first_name=random_name(),
                    birth_date=random_birth_date(),
                    gender=random_gender(),
                    role=User.Role.AGENT,
                    status=User.Status.ACTIVE,
                    is_active=True,
                    agent_services=list(services),
                    agent_cities=[area.id],
                    agent_states=[area.state_code],
                    agent_cities_by_state={area.state_code: [area.id]},
                )
                user.set_password("1234")
                user.save()
                created += 1

                if (i + 1) % 50 == 0:
                    self.stdout.write(f"  ... {i + 1}/{len(areas)} 생성됨")

        self.stdout.write(self.style.SUCCESS(f"완료: {created}개 에이전트 계정 생성 (비밀번호: 1234)"))
