"""
수동 테스트: 제출(submission)에 대해 스케줄 초안(ServiceSchedulePlan + Items) 생성.
Usage: python manage.py generate_schedule_draft <submission_id>
"""
from django.core.management.base import BaseCommand

from survey.models import SurveySubmission
from settlement.scheduling_engine import generate_schedule_draft


class Command(BaseCommand):
    help = '제출(submission_id)에 대해 ML/규칙 기반 스케줄 초안(ServiceSchedulePlan)을 생성합니다.'

    def add_arguments(self, parser):
        parser.add_argument('submission_id', type=int, help='SurveySubmission id')

    def handle(self, *args, **options):
        sid = options['submission_id']
        try:
            submission = SurveySubmission.objects.get(pk=sid)
        except SurveySubmission.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'SurveySubmission id={sid} not found.'))
            return
        try:
            plan = generate_schedule_draft(submission, quote=None, plan=None, actor=None)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Created ServiceSchedulePlan id={plan.id} (version={plan.version}, '
                    f'items={plan.items.count()}) for submission_id={sid}.'
                )
            )
            for it in plan.items.order_by('sort_order')[:20]:
                self.stdout.write(
                    f'  - {it.service_code} @ {it.starts_at} score={it.source_score} '
                    f'review={bool(it.notes)}'
                )
            if plan.items.count() > 20:
                self.stdout.write(f'  ... and {plan.items.count() - 20} more items.')
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'generate_schedule_draft failed: {e}'))
            raise
