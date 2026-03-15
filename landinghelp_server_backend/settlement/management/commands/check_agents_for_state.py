"""
DB에 등록된 Agent 목록과 지정한 주(State) 담당 매칭 여부 확인.
사용: python manage.py check_agents_for_state [STATE_CODE]
예: python manage.py check_agents_for_state NC
    python manage.py check_agents_for_state   (미입력 시 전체 Agent 목록)
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from settlement.constants import _normalize_state_code

User = get_user_model()


class Command(BaseCommand):
    help = 'Agent 목록 및 지정 주(State) 담당 매칭 확인 (예: check_agents_for_state NC)'

    def add_arguments(self, parser):
        parser.add_argument(
            'state',
            nargs='?',
            default='',
            help='2글자 State 코드 또는 주 이름 (예: NC, North Carolina)',
        )

    def handle(self, *args, **options):
        state_raw = (options.get('state') or '').strip()
        state_code = _normalize_state_code(state_raw) if state_raw else ''

        agents = User.objects.filter(role=User.Role.AGENT).order_by('id')
        self.stdout.write(f'전체 AGENT 수: {agents.count()}')
        self.stdout.write('')

        for u in agents:
            status = getattr(u, 'status', '') or ''
            active = status == User.Status.ACTIVE
            states = getattr(u, 'agent_states', None) or []
            services = getattr(u, 'agent_services', None) or []
            has_nc = 'NC' in states if isinstance(states, list) else False
            matches = state_code and state_code in states if isinstance(states, list) else False
            self.stdout.write(
                f"  id={u.id} username={u.username!r} status={status} "
                f"agent_states={states} agent_services(개)={len(services)}"
            )
            if state_code:
                self.stdout.write(
                    f"    -> state_code={state_code!r} 매칭: {matches} (agent_states에 포함 여부)"
                )
            self.stdout.write('')

        if state_code:
            qs = User.objects.filter(
                role=User.Role.AGENT,
                status=User.Status.ACTIVE,
            ).filter(agent_states__contains=[state_code])
            count = qs.count()
            self.stdout.write(f'[조건] role=AGENT, status=ACTIVE, agent_states__contains=[{state_code!r}] => {count}명')
            if count == 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'{state_code} 담당 Agent가 없다고 나오는 경우: '
                        '위 목록에서 AGENT의 agent_states에 해당 코드가 들어 있는지 확인하세요. '
                        'Admin에서 User(에이전트) → 커버 주(State)에 해당 주 코드를 추가하세요.'
                    )
                )
