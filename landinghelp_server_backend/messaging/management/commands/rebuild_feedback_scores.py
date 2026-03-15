from django.core.management.base import BaseCommand

from messaging.feedback_scores import export_learning_dataset, rebuild_feedback_scores
from messaging.models import PageKeyFeedbackScore


class Command(BaseCommand):
    help = 'CustomerRequestLearningSummary를 집계해 페이지 추천 보정 점수(PageKeyFeedbackScore)를 재계산합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--top',
            type=int,
            default=10,
            help='재계산 후 score_boost 상위 N개를 출력합니다. (기본 10)',
        )
        parser.add_argument(
            '--export',
            type=str,
            default='',
            help='학습 데이터 JSON export 파일 경로 (옵션)',
        )
        parser.add_argument(
            '--min-quality',
            type=str,
            default='medium',
            choices=['weak', 'medium', 'strong'],
            help='export 시 포함할 최소 label_quality (기본 medium)',
        )

    def handle(self, *args, **options):
        top_n = max(int(options.get('top') or 10), 0)
        result = rebuild_feedback_scores()
        updated = int((result or {}).get('updated') or 0)

        self.stdout.write(self.style.SUCCESS(f'feedback score rebuild done: updated={updated}'))

        export_path = (options.get('export') or '').strip()
        if export_path:
            exported = export_learning_dataset(export_path, min_quality=options.get('min_quality') or 'medium')
            self.stdout.write(
                self.style.SUCCESS(
                    f"learning dataset exported: count={exported.get('count', 0)} path={exported.get('path', export_path)}"
                )
            )

        if top_n <= 0:
            return

        self.stdout.write('top boosted page keys:')
        rows = PageKeyFeedbackScore.objects.order_by('-score_boost', '-total_seen')[:top_n]
        for row in rows:
            self.stdout.write(
                f'  {row.page_key}: boost={row.score_boost:+.4f} '
                f'seen={row.total_seen} up={row.thumbs_up_count} down={row.thumbs_down_count} '
                f'pos={row.positive_label_count} neg={row.negative_label_count}'
            )
