# content: 컨텐츠 (옵션 A: allowed_roles + min_tier)
from django.db import models
from django.conf import settings
from django.utils.text import slugify
from translations.utils import DisplayKey


class Content(models.Model):
    """컨텐츠"""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', '초안'
        PUBLISHED = 'PUBLISHED', '발행'

    class Tier(models.IntegerChoices):
        BASIC = 1, '베이직'
        STANDARD = 2, '스탠다드'
        PREMIUM = 3, '프리미엄'

    ROLE_CHOICES = [
        ('ADMIN', '관리자'),
        ('AGENT', '에이전트'),
        ('CUSTOMER', '고객'),
        ('GUEST', '손님(비로그인)'),
    ]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    category = models.CharField(max_length=100, blank=True)
    summary = models.TextField(blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    allowed_roles = models.JSONField(
        default=list,
        blank=True,
        help_text=DisplayKey('접근 허용 역할 (GUEST=비로그인, CUSTOMER, AGENT, ADMIN)'),
    )
    min_tier = models.PositiveSmallIntegerField(
        choices=Tier.choices,
        default=Tier.BASIC,
    )
    is_public = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_contents',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = DisplayKey('컨텐츠')  # 컨텐츠
        verbose_name_plural = DisplayKey('컨텐츠')
        ordering = ('-updated_at',)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)


class CarouselSlide(models.Model):
    """캐러셀 슬라이드 (홈인트로, 정착서비스, 기업서비스, 광고)"""

    class Placement(models.TextChoices):
        HOME_INTRO = 'HOME_INTRO', '홈인트로'
        SETTLEMENT = 'SETTLEMENT', '정착서비스'
        CORPORATE = 'CORPORATE', '기업서비스'
        AD = 'AD', '광고'

    class BackgroundType(models.TextChoices):
        IMAGE = 'IMAGE', '이미지'
        GRADIENT = 'GRADIENT', '그라데이션'

    placement = models.CharField(
        max_length=20,
        choices=Placement.choices,
        default=Placement.HOME_INTRO,
        verbose_name=DisplayKey('노출 위치'),  # 노출 위치
        db_index=True,
    )
    title = models.CharField(max_length=200, verbose_name=DisplayKey('제목'))  # 제목
    subtitle = models.CharField(max_length=300, blank=True, verbose_name=DisplayKey('부제목'))  # 부제목
    link_url = models.URLField(blank=True, verbose_name=DisplayKey('링크 URL'), help_text=DisplayKey('광고 등 클릭 시 이동할 URL'))  # 링크 URL
    order = models.PositiveIntegerField(default=0, verbose_name=DisplayKey('정렬'))  # 정렬
    is_active = models.BooleanField(default=True, verbose_name=DisplayKey('표시'))  # 표시
    background_type = models.CharField(
        max_length=20,
        choices=BackgroundType.choices,
        default=BackgroundType.GRADIENT,
    )
    image = models.ImageField(
        upload_to='carousel/',
        blank=True,
        null=True,
        verbose_name=DisplayKey('배경 이미지'),  # 배경 이미지
    )
    gradient_css = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=DisplayKey('그라데이션 CSS'),  # 그라데이션 CSS
        help_text=DisplayKey('예: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = DisplayKey('캐러셀 슬라이드')  # 캐러셀 슬라이드
        verbose_name_plural = DisplayKey('캐러셀 슬라이드')
        ordering = ['placement', 'order', 'id']

    def __str__(self):
        return self.title


class CorporateAdRequest(models.Model):
    """기업 광고 등록 신청 (Admin 검토 후 캐러셀 광고로 승인 가능)"""

    class Status(models.TextChoices):
        PENDING = 'PENDING', '검토 대기'
        APPROVED = 'APPROVED', '승인'
        REJECTED = 'REJECTED', '반려'

    company_name = models.CharField(max_length=200, verbose_name=DisplayKey('회사/업체명'))  # 회사/업체명
    contact_name = models.CharField(max_length=100, verbose_name=DisplayKey('담당자명'))  # 담당자명
    email = models.EmailField(verbose_name=DisplayKey('이메일'))  # 이메일
    phone = models.CharField(max_length=30, blank=True, verbose_name=DisplayKey('연락처'))  # 연락처
    ad_title = models.CharField(max_length=200, verbose_name=DisplayKey('광고 제목'))  # 광고 제목
    ad_subtitle = models.CharField(max_length=300, blank=True, verbose_name=DisplayKey('광고 부제목'))  # 광고 부제목
    link_url = models.URLField(verbose_name=DisplayKey('링크 URL'))  # 링크 URL
    memo = models.TextField(blank=True, verbose_name=DisplayKey('추가 요청사항'))  # 추가 요청사항
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = DisplayKey('광고 등록 신청')  # 광고 등록 신청
        verbose_name_plural = DisplayKey('광고 등록 신청')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} - {self.ad_title}"


# Proxy models for admin (placement별 별도 관리)
class HomeIntroSlide(CarouselSlide):
    class Meta:
        proxy = True
        verbose_name = DisplayKey('캐러셀 (홈인트로)')  # 캐러셀 (홈인트로)
        verbose_name_plural = DisplayKey('캐러셀 (홈인트로)')


class SettlementCarouselSlide(CarouselSlide):
    class Meta:
        proxy = True
        verbose_name = DisplayKey('캐러셀 (정착서비스)')  # 캐러셀 (정착서비스)
        verbose_name_plural = DisplayKey('캐러셀 (정착서비스)')


class CorporateCarouselSlide(CarouselSlide):
    class Meta:
        proxy = True
        verbose_name = DisplayKey('캐러셀 (기업서비스)')  # 캐러셀 (기업서비스)
        verbose_name_plural = DisplayKey('캐러셀 (기업서비스)')


class AdCarouselSlide(CarouselSlide):
    class Meta:
        proxy = True
        verbose_name = DisplayKey('캐러셀 (광고)')  # 캐러셀 (광고)
        verbose_name_plural = DisplayKey('캐러셀 (광고)')
