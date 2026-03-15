from django.contrib.auth import get_user_model
from django.test import TestCase

from survey.models import SurveySubmission


User = get_user_model()


class UserRoleHelperTests(TestCase):
    def setUp(self):
        self.super_admin = User.objects.create_user(
            username='super_admin_helper',
            email='super_admin_helper@test.com',
            password='pass1234',
            role=User.Role.SUPER_ADMIN,
        )
        self.admin = User.objects.create_user(
            username='admin_helper',
            email='admin_helper@test.com',
            password='pass1234',
            role=User.Role.ADMIN,
        )
        self.supervisor = User.objects.create_user(
            username='supervisor_helper',
            email='supervisor_helper@test.com',
            password='pass1234',
            role=User.Role.SUPERVISOR,
        )
        self.hq_staff = User.objects.create_user(
            username='hq_staff_helper',
            email='hq_staff_helper@test.com',
            password='pass1234',
            role=User.Role.HQ_STAFF,
        )
        self.customer = User.objects.create_user(
            username='customer_helper',
            email='customer_helper@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.customer_other = User.objects.create_user(
            username='customer_other_helper',
            email='customer_other_helper@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
        )
        self.agent = User.objects.create_user(
            username='agent_helper',
            email='agent_helper@test.com',
            password='pass1234',
            role=User.Role.AGENT,
        )

        self.customer_submission = SurveySubmission.objects.create(
            user=self.customer,
            email=self.customer.email,
            status=SurveySubmission.Status.SUBMITTED,
            answers={},
        )

    def test_internal_staff_roles_are_detected(self):
        self.assertTrue(self.super_admin.is_internal_staff())
        self.assertTrue(self.admin.is_internal_staff())
        self.assertTrue(self.supervisor.is_internal_staff())
        self.assertTrue(self.hq_staff.is_internal_staff())
        self.assertFalse(self.customer.is_internal_staff())
        self.assertFalse(self.agent.is_internal_staff())

    def test_staff_flag_backwards_compatibility_is_preserved(self):
        legacy_staff = User.objects.create_user(
            username='legacy_staff_helper',
            email='legacy_staff_helper@test.com',
            password='pass1234',
            role=User.Role.CUSTOMER,
            is_staff=True,
        )
        self.assertTrue(legacy_staff.is_internal_staff())
        self.assertTrue(legacy_staff.can_participate_in_hq_workspace())

    def test_quote_schedule_and_document_permissions_follow_internal_staff(self):
        for user in [self.super_admin, self.admin, self.supervisor, self.hq_staff]:
            self.assertTrue(user.can_send_quote())
            self.assertTrue(user.can_finalize_schedule())
            self.assertTrue(user.can_manage_case_documents())

        self.assertFalse(self.customer.can_send_quote())
        self.assertFalse(self.agent.can_finalize_schedule())
        self.assertFalse(self.customer.can_manage_case_documents())

    def test_customer_private_docs_visibility(self):
        self.assertTrue(self.admin.can_view_customer_private_docs(self.customer_submission))
        self.assertTrue(self.customer.can_view_customer_private_docs(self.customer_submission))
        self.assertFalse(self.customer_other.can_view_customer_private_docs(self.customer_submission))
        self.assertFalse(self.agent.can_view_customer_private_docs(self.customer_submission))

    def test_workspace_participation_helpers(self):
        self.assertTrue(self.supervisor.can_participate_in_hq_workspace())
        self.assertTrue(self.hq_staff.can_participate_in_hq_workspace())
        self.assertFalse(self.customer.can_participate_in_hq_workspace())

        self.assertTrue(self.customer.can_participate_in_local_workspace())
        self.assertTrue(self.agent.can_participate_in_local_workspace())
        self.assertTrue(self.admin.can_participate_in_local_workspace())
