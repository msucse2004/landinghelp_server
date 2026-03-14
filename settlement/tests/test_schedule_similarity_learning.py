from datetime import datetime, timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from settlement.scheduling_engine import (
    apply_grouping_pattern_adjustments,
    compute_similarity_score,
    learn_historical_pattern_priors,
    rank_historical_examples,
)


class ScheduleSimilarityLearningTests(SimpleTestCase):
    def _base_current_features(self):
        return {
            'state_code': 'CA',
            'city': 'Irvine',
            'requested_service_codes': ['SVC_A', 'SVC_B', 'SVC_C'],
            'dependency_sensitive_service_codes': ['SVC_A', 'SVC_B'],
            'service_count': 3,
            'remaining_days_to_entry': 20,
            'household_size': 3,
            'has_special_requirements': True,
            'preferred_support_mode': 'chat',
            'in_person_service_count': 2,
        }

    def _aware(self, year, month, day, hour=9):
        return timezone.make_aware(datetime(year, month, day, hour, 0, 0))

    def test_similarity_ranking_behaves_sensibly(self):
        current = self._base_current_features()
        good = {
            'plan_id': 1,
            'item_id': 1,
            'state_code': 'CA',
            'city': 'Irvine',
            'requested_service_codes': ['SVC_A', 'SVC_B', 'SVC_C'],
            'dependency_sensitive_service_codes': ['SVC_A', 'SVC_B'],
            'service_count': 3,
            'remaining_days_to_entry': 18,
            'household_size': 3,
            'has_special_requirements': True,
            'preferred_support_mode': 'chat',
            'in_person_service_count': 2,
        }
        weak = {
            'plan_id': 2,
            'item_id': 2,
            'state_code': 'TX',
            'city': 'Austin',
            'requested_service_codes': ['SVC_Z'],
            'dependency_sensitive_service_codes': ['SVC_Z'],
            'service_count': 1,
            'remaining_days_to_entry': 90,
            'household_size': 1,
            'has_special_requirements': False,
            'preferred_support_mode': 'phone',
            'in_person_service_count': 0,
        }

        score_good = compute_similarity_score(current, good)
        score_weak = compute_similarity_score(current, weak)
        self.assertGreater(score_good, score_weak)

        ranked = rank_historical_examples(current, [weak, good])
        self.assertEqual(ranked[0][1]['plan_id'], 1)

    def test_service_day_offset_prior_extraction(self):
        current = self._base_current_features()
        rows = []

        starts_1 = self._aware(2026, 5, 5, 10)
        starts_2 = self._aware(2026, 5, 6, 11)
        starts_3 = self._aware(2026, 5, 7, 10)

        rows.extend([
            {
                'plan_id': 101,
                'item_id': 1,
                'service_code': 'SVC_A',
                'starts_at': starts_1,
                'days_from_entry': 4,
                'state_code': 'CA',
                'city': 'Irvine',
                'requested_service_codes': ['SVC_A', 'SVC_B', 'SVC_C'],
                'dependency_sensitive_service_codes': ['SVC_A', 'SVC_B'],
                'service_count': 3,
                'remaining_days_to_entry': 22,
                'household_size': 3,
                'has_special_requirements': True,
                'preferred_support_mode': 'chat',
                'in_person_service_count': 2,
                'sort_order': 1,
            },
            {
                'plan_id': 102,
                'item_id': 2,
                'service_code': 'SVC_A',
                'starts_at': starts_2,
                'days_from_entry': 5,
                'state_code': 'CA',
                'city': 'Irvine',
                'requested_service_codes': ['SVC_A', 'SVC_B', 'SVC_C'],
                'dependency_sensitive_service_codes': ['SVC_A', 'SVC_B'],
                'service_count': 3,
                'remaining_days_to_entry': 19,
                'household_size': 3,
                'has_special_requirements': True,
                'preferred_support_mode': 'chat',
                'in_person_service_count': 2,
                'sort_order': 1,
            },
            {
                'plan_id': 103,
                'item_id': 3,
                'service_code': 'SVC_A',
                'starts_at': starts_3,
                'days_from_entry': 6,
                'state_code': 'CA',
                'city': 'Irvine',
                'requested_service_codes': ['SVC_A', 'SVC_B', 'SVC_C'],
                'dependency_sensitive_service_codes': ['SVC_A', 'SVC_B'],
                'service_count': 3,
                'remaining_days_to_entry': 20,
                'household_size': 3,
                'has_special_requirements': True,
                'preferred_support_mode': 'chat',
                'in_person_service_count': 2,
                'sort_order': 1,
            },
        ])

        priors = learn_historical_pattern_priors(current, rows)
        svc_prior = priors['service_day_offset_priors'].get('SVC_A')

        self.assertIsNotNone(svc_prior)
        self.assertIn(svc_prior['day_offset'], (5,))
        self.assertGreaterEqual(svc_prior['sample_count'], 3)

    def test_grouping_patterns_reused_when_relevant(self):
        day1 = self._aware(2026, 8, 10, 9)
        day2 = self._aware(2026, 8, 11, 14)

        placements = [
            {
                'code': 'SVC_A',
                'starts_at': day1,
                'ends_at': day1 + timedelta(hours=1),
                'duration_minutes': 60,
                'reason': 'evidence=historical-match',
            },
            {
                'code': 'SVC_B',
                'starts_at': day2,
                'ends_at': day2 + timedelta(hours=1),
                'duration_minutes': 60,
                'reason': 'evidence=historical-match',
            },
        ]
        grouping_priors = {
            ('SVC_A', 'SVC_B'): {'confidence': 0.72, 'support_weight': 2.4},
        }

        adjusted = apply_grouping_pattern_adjustments(placements, grouping_priors)

        self.assertEqual(adjusted[0]['starts_at'].date(), adjusted[1]['starts_at'].date())
        self.assertIn('evidence=grouping-prior', adjusted[1]['reason'])

    def test_sparse_history_falls_back_without_crashing(self):
        current = self._base_current_features()
        priors = learn_historical_pattern_priors(current, [])

        self.assertEqual(priors['selected_plan_count'], 0)
        self.assertEqual(priors['service_day_offset_priors'], {})
        self.assertEqual(priors['sequence_priors_by_service'], {})
        self.assertEqual(priors['grouping_pair_priors'], {})
