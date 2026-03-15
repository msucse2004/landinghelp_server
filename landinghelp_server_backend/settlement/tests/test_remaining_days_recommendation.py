from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from settlement.models import ServiceScheduleItem
from settlement.scheduling_engine import generate_schedule_draft
from survey.models import SurveyQuestion, SurveySubmission


User = get_user_model()


class RemainingDaysRecommendationTests(TestCase):
    def setUp(self):
        SurveyQuestion.objects.create(
            key='entry_date_remaining_days',
            label='입국일',
            field_type=SurveyQuestion.FieldType.TEXT,
            step=1,
            order=1,
            required=False,
            is_active=True,
            quote_relevant=True,
            quote_mapping_key='entry_date',
            quote_value_type='date',
        )
        self._user_seq = 0

    def _submission(self, entry_date_text):
        self._user_seq += 1
        user = User.objects.create_user(
            username=f'remaining_days_user_{self._user_seq}',
            email=f'remaining_days_user_{self._user_seq}@test.com',
            password='testpass123',
        )
        services = ['svc_a', 'svc_b', 'svc_c']
        return SurveySubmission.objects.create(
            user=user,
            email=user.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={
                'entry_date_remaining_days': entry_date_text,
                'service_delivery_mode': 'per_service',
                'service_delivery_per_service': {
                    'svc_a': 'agent_direct',
                    'svc_b': 'agent_direct',
                    'svc_c': 'agent_direct',
                },
            },
            requested_required_services=services,
            requested_optional_services=[],
        )

    def _draft_dates_and_reasons(self, submission):
        plan = generate_schedule_draft(
            submission,
            service_type_whitelist={ServiceScheduleItem.ServiceType.IN_PERSON_AGENT},
        )
        items = list(plan.items.order_by('sort_order', 'starts_at', 'id'))
        starts = [it.starts_at for it in items if it.starts_at]
        dates = [it.starts_at.date() for it in items if it.starts_at]
        reasons = [it.source_reason or '' for it in items]
        return starts, dates, reasons

    def test_imminent_entry_case(self):
        today = timezone.localdate()
        imminent_entry = (today + timedelta(days=2)).isoformat()
        submission = self._submission(imminent_entry)

        _starts, dates, reasons = self._draft_dates_and_reasons(submission)

        self.assertTrue(dates)
        self.assertTrue(all(d >= today for d in dates))
        self.assertLessEqual((max(dates) - min(dates)).days, 2)
        self.assertTrue(all('remaining-days-band=urgent' in r for r in reasons))

    def test_moderate_lead_time_case(self):
        today = timezone.localdate()
        moderate_entry = (today + timedelta(days=30)).isoformat()
        submission = self._submission(moderate_entry)

        _starts, dates, reasons = self._draft_dates_and_reasons(submission)

        self.assertTrue(dates)
        self.assertTrue(all(d >= today for d in dates))
        self.assertGreaterEqual((max(dates) - min(dates)).days, 2)
        self.assertLessEqual((max(dates) - min(dates)).days, 21)
        self.assertTrue(all('remaining-days-band=normal' in r for r in reasons))

    def test_long_lead_time_case(self):
        today = timezone.localdate()
        long_entry = (today + timedelta(days=120)).isoformat()
        submission = self._submission(long_entry)

        _starts, dates, reasons = self._draft_dates_and_reasons(submission)

        self.assertTrue(dates)
        self.assertTrue(all(d >= today for d in dates))
        sorted_dates = sorted(dates)
        gaps = [
            (sorted_dates[idx + 1] - sorted_dates[idx]).days
            for idx in range(len(sorted_dates) - 1)
        ]
        self.assertTrue(all(g >= 2 for g in gaps))
        self.assertTrue(all('remaining-days-band=long' in r for r in reasons))

    def test_past_entry_and_malformed_date_behavior(self):
        today = timezone.localdate()

        past_entry = (today - timedelta(days=10)).isoformat()
        past_submission = self._submission(past_entry)
        past_starts, past_dates, past_reasons = self._draft_dates_and_reasons(past_submission)
        self.assertTrue(past_dates)
        self.assertTrue(all(dt >= timezone.now() - timedelta(minutes=1) for dt in past_starts))
        self.assertTrue(all('remaining-days-band=urgent' in r for r in past_reasons))

        malformed_submission = self._submission('not-a-date')
        malformed_starts, malformed_dates, malformed_reasons = self._draft_dates_and_reasons(malformed_submission)
        self.assertTrue(malformed_dates)
        self.assertTrue(all(dt >= timezone.now() - timedelta(minutes=1) for dt in malformed_starts))
        self.assertTrue(all('remaining-days-band=normal' in r for r in malformed_reasons))
