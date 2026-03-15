from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class LabelAccuracyReportViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='staff_label_view',
            email='staff_label_view@test.com',
            password='p',
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username='normal_label_view',
            email='normal_label_view@test.com',
            password='p',
            is_staff=False,
        )

    def test_api_label_accuracy_report_staff_access(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('app_debug_label_accuracy_api'), {'limit': 5, 'period': '30'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('total_manual_labeled', data)
        self.assertEqual(data.get('period_days'), 30)
        self.assertIn('top_wrong_predicted_pages', data)
        self.assertIn('top_wrong_predicted_intents', data)

    def test_api_label_accuracy_report_non_staff_blocked(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('app_debug_label_accuracy_api'), {'limit': 5})
        self.assertNotEqual(resp.status_code, 200)

    def test_api_label_accuracy_report_invalid_period(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('app_debug_label_accuracy_api'), {'limit': 5, 'period': 'bad'})
        self.assertEqual(resp.status_code, 400)

    def test_api_label_accuracy_report_custom_days(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('app_debug_label_accuracy_api'),
            {'limit': 5, 'period': 'custom', 'days': '14'},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get('period_days'), 14)

    def test_api_label_accuracy_report_custom_days_invalid(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('app_debug_label_accuracy_api'),
            {'limit': 5, 'period': 'custom', 'days': 'x'},
        )
        self.assertEqual(resp.status_code, 400)

    def test_debug_label_accuracy_page_custom_days_invalid_fallback(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('app_debug_label_accuracy'),
            {'limit': 5, 'period': 'custom', 'days': '0'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['period'], 'all')

    def test_debug_label_accuracy_page_custom_days_kept(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            reverse('app_debug_label_accuracy'),
            {'limit': 5, 'period': 'custom', 'days': '21'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['period'], 'custom')
        self.assertEqual(resp.context['days'], '21')
