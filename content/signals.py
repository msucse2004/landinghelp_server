"""
관리자가 캐러셀/콘텐츠 등 텍스트를 저장하면 해당 값을 키로 지원 모든 언어 번역 후 CSV(StaticTranslation)에 추가.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CarouselSlide, Content, CorporateAdRequest


def _translate_text_field(value: str, source_lang: str = 'ko') -> None:
    if not value or not value.strip():
        return
    try:
        from translations.services import translate_and_save_to_static
        translate_and_save_to_static(value.strip(), source_lang=source_lang)
    except Exception:
        pass


@receiver(post_save, sender=CarouselSlide)
def carousel_slide_saved(sender, instance, **kwargs):
    """캐러셀 제목/부제목을 키로 모든 지원 언어 번역 후 CSV에 저장."""
    if instance.title:
        _translate_text_field(instance.title)
    if instance.subtitle:
        _translate_text_field(instance.subtitle)


@receiver(post_save, sender=Content)
def content_saved(sender, instance, **kwargs):
    """콘텐츠 제목/요약을 키로 모든 지원 언어 번역 후 CSV에 저장."""
    if instance.title:
        _translate_text_field(instance.title)
    if instance.summary:
        _translate_text_field(instance.summary)


@receiver(post_save, sender=CorporateAdRequest)
def corporate_ad_request_saved(sender, instance, **kwargs):
    """광고 등록 신청 제목/부제목을 키로 모든 지원 언어 번역 후 CSV에 저장."""
    if instance.ad_title:
        _translate_text_field(instance.ad_title)
    if instance.ad_subtitle:
        _translate_text_field(instance.ad_subtitle)
