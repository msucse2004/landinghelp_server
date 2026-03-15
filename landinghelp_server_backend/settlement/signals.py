# 관리자에서 약속(AgentAppointmentRequest) 삭제 시 고객 일정에서 해당 슬롯 제거
# 서비스 항목(SettlementService) 저장 시 고정 번역에 키/번역 추가
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import AgentAppointmentRequest, SettlementService, UserSettlementPlan


@receiver(post_delete, sender=AgentAppointmentRequest)
def remove_appointment_from_customer_schedule(sender, instance, **kwargs):
    """
    약속이 삭제되면 해당 고객(customer)의 정착 플랜 일정(service_schedule)에서
    동일한 service_date, service_code 슬롯을 제거하여 customer 화면에서도 사라지게 함.
    (Conversation 등 연관 데이터는 FK on_delete=CASCADE로 이미 삭제됨)
    """
    if not instance.customer_id:
        return
    try:
        plan = UserSettlementPlan.objects.get(user_id=instance.customer_id)
    except UserSettlementPlan.DoesNotExist:
        return
    schedule = plan.service_schedule or {}
    if not isinstance(schedule, dict):
        return
    date_str = str(instance.service_date)
    code = (instance.service_code or '').strip()
    if date_str not in schedule or not isinstance(schedule[date_str], list):
        return
    new_items = [item for item in schedule[date_str] if isinstance(item, dict) and (item.get('code') or '').strip() != code]
    if not new_items:
        schedule = {k: v for k, v in schedule.items() if k != date_str}
    else:
        schedule = dict(schedule)
        schedule[date_str] = new_items
    plan.service_schedule = schedule
    plan.save(update_fields=['service_schedule'])


@receiver(post_save, sender=SettlementService)
def settlement_service_saved(sender, instance, **kwargs):
    """서비스 항목 이름을 고정 번역에 등록하고 지원 언어로 번역 후 CSV에 저장."""
    if not getattr(instance, 'name', None) or not str(instance.name).strip():
        return
    try:
        from translations.services import translate_and_save_to_static
        translate_and_save_to_static(str(instance.name).strip(), source_lang='ko')
    except Exception:
        pass
