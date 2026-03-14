from django.core.management.base import BaseCommand

from accounts.agent_leveling import evaluate_all_agents


class Command(BaseCommand):
    help = '모든 Agent의 레벨/점수를 재계산합니다.'

    def handle(self, *args, **options):
        summary = evaluate_all_agents()
        self.stdout.write(self.style.SUCCESS(
            f"Agent 레벨 재계산 완료: {summary.get('processed', 0)}명"
        ))
