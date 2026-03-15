from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AppEntryRoleRoutingTests(TestCase):
    def setUp(self):
        self.url = reverse('app_entry')
        self.users = {
            'super_admin': User.objects.create_user(
                username='route_super_admin',
                email='route_super_admin@test.com',
                password='pass1234',
                role=User.Role.SUPER_ADMIN,
            ),
            'admin': User.objects.create_user(
                username='route_admin',
                email='route_admin@test.com',
                password='pass1234',
                role=User.Role.ADMIN,
            ),
            'supervisor': User.objects.create_user(
                username='route_supervisor',
                email='route_supervisor@test.com',
                password='pass1234',
                role=User.Role.SUPERVISOR,
            ),
            'hq_staff': User.objects.create_user(
                username='route_hq_staff',
                email='route_hq_staff@test.com',
                password='pass1234',
                role=User.Role.HQ_STAFF,
            ),
            'agent': User.objects.create_user(
                username='route_agent',
                email='route_agent@test.com',
                password='pass1234',
                role=User.Role.AGENT,
            ),
            'customer': User.objects.create_user(
                username='route_customer',
                email='route_customer@test.com',
                password='pass1234',
                role=User.Role.CUSTOMER,
            ),
        }

    def test_hq_workspace_roles_route_to_admin_dashboard(self):
        for key in ('super_admin', 'admin', 'supervisor', 'hq_staff'):
            self.client.force_login(self.users[key])
            response = self.client.get(self.url)
            self.assertRedirects(response, reverse('app_admin_dashboard'), fetch_redirect_response=False)
            self.client.logout()

    def test_agent_routes_to_agent_dashboard(self):
        self.client.force_login(self.users['agent'])
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('app_agent_dashboard'), fetch_redirect_response=False)

    def test_customer_routes_to_customer_dashboard(self):
        self.client.force_login(self.users['customer'])
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('app_customer_dashboard'), fetch_redirect_response=False)
