"""
아이디: Agent_{State}_{언어코드} (예: Agent_NC_KR, Agent_CA_EN)
비밀번호: 1234
지원 State × 지원 언어별로 Agent 계정 생성. 지원 서비스는 전부 선택, 그 외 항목은 랜덤.

실행: python manage.py create_agent_accounts
      python manage.py create_agent_accounts --dry-run
"""
import random
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.utils import IntegrityError

from accounts.models import User
from settlement.models import SettlementService

# settlement.forms.US_STATES에서 코드만 사용 (빈 문자열 제외)
STATE_CODES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI',
    'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN',
    'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH',
    'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA',
    'WV', 'WI', 'WY', 'DC',
]

# User.PREFERRED_LANGUAGE_CHOICES → 아이디 접미사 (예: Agent_NC_KR)
LANG_TO_SUFFIX = {
    'ko': 'KR',
    'en': 'EN',
    'es': 'ES',
    'zh-hans': 'ZHS',
    'zh-hant': 'ZHT',
    'vi': 'VI',
}

FIRST_NAMES = [
    'James', 'John', 'Robert', 'Michael', 'William', 'David', 'Joseph', 'Daniel',
    'Emma', 'Olivia', 'Ava', 'Sophia', 'Isabella', 'Mia', 'Charlotte', 'Amelia',
    '민준', '서준', '도윤', '예준', '시우', '하준', '지호', '주원',
    '서연', '서윤', '지우', '하윤', '하은', '민서', '지유', '수아',
]
LAST_NAMES = [
    'Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis',
    'Kim', 'Park', 'Lee', 'Choi', 'Jung', 'Kang', 'Cho', 'Yoon',
]


def random_birth_date():
    year = random.randint(1980, 2000)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return date(year, month, day)


def random_gender():
    return random.choice([User.Gender.M, User.Gender.F])


# 생성되는 모든 Agent 계정의 이메일 주소 (동일 주소 사용)
DEFAULT_AGENT_EMAIL = 'msucse.bryan@gmail.com'


class Command(BaseCommand):
    help = '모든 지원 State × 지원 언어별 Agent 계정 생성 (아이디: Agent_{State}_{언어}, 비밀번호: 1234)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 생성 없이 생성 예정 개수만 출력',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        lang_codes = list(LANG_TO_SUFFIX.keys())
        service_ids = list(
            SettlementService.objects.filter(is_active=True).values_list('id', flat=True)
        )

        if not service_ids:
            self.stdout.write(self.style.WARNING('활성 서비스가 없습니다. settlement 앱 서비스를 먼저 등록하세요.'))
            return

        total = len(STATE_CODES) * len(lang_codes)
        self.stdout.write(
            f'State 수: {len(STATE_CODES)}, 언어 수: {len(lang_codes)}, '
            f'서비스 수: {len(service_ids)} → 생성 예정 계정 수: {total}'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f'[Dry Run] {total}개 Agent 계정 생성 예정 (비밀번호: 1234)'))
            for state in STATE_CODES[:3]:
                for lang in lang_codes[:2]:
                    suffix = LANG_TO_SUFFIX[lang]
                    self.stdout.write(f'  예: Agent_{state}_{suffix}')
            if total > 6:
                self.stdout.write('  ...')
            return

        created = 0
        skipped = 0
        with transaction.atomic():
            for state in STATE_CODES:
                for lang in lang_codes:
                    suffix = LANG_TO_SUFFIX[lang]
                    username = f'Agent_{state}_{suffix}'
                    if User.objects.filter(username=username).exists():
                        skipped += 1
                        continue

                    email = DEFAULT_AGENT_EMAIL

                    try:
                        user = User(
                            username=username,
                            email=email,
                            first_name=random.choice(FIRST_NAMES),
                            last_name=random.choice(LAST_NAMES),
                            birth_date=random_birth_date(),
                            gender=random_gender(),
                            role=User.Role.AGENT,
                            status=User.Status.ACTIVE,
                            is_active=True,
                            preferred_language=lang,
                            agent_services=list(service_ids),
                            agent_states=[state],
                            agent_cities=[],
                            agent_cities_by_state={state: []},
                            accept_rate=None,
                        )
                        user.set_password('1234')
                        user.save()
                        created += 1

                        if created % 50 == 0:
                            self.stdout.write(f'  ... {created}개 생성됨')
                    except IntegrityError:
                        skipped += 1
                        continue

        self.stdout.write(
            self.style.SUCCESS(
                f'완료: {created}개 생성, {skipped}개 건너뜀(이미 존재). '
                f'아이디 형식: Agent_{{State}}_{{언어}}, 비밀번호: 1234'
            )
        )
