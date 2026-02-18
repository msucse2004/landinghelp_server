# billing: 가입 시 기본 플랜 자동 할당

from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User
from .models import Plan, Subscription


@receiver(post_save, sender=User)
def assign_default_plan_on_signup(sender, instance, created, **kwargs):
    """가입 시 역할에 따라 기본 플랜 할당"""
    if not created:
        return
    plan_code = Plan.Code.C_BASIC if instance.role == User.Role.CUSTOMER else Plan.Code.P_BASIC
    plan = Plan.objects.filter(code=plan_code, is_active=True).first()
    if plan:
        Subscription.objects.create(user=instance, plan=plan, status=Subscription.Status.ACTIVE)
