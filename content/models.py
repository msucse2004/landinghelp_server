# content: 컨텐츠 (옵션 A: allowed_roles + min_tier)
from django.db import models
from django.conf import settings
from django.utils.text import slugify


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
        help_text='접근 허용 역할 (GUEST=비로그인, CUSTOMER, AGENT, ADMIN)',
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
        verbose_name = '컨텐츠'
        verbose_name_plural = '컨텐츠'
        ordering = ('-updated_at',)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
        super().save(*args, **kwargs)


class CarouselSlide(models.Model):
    """홈 인트로 캐러셀 슬라이드"""

    class BackgroundType(models.TextChoices):
        IMAGE = 'IMAGE', '이미지'
        GRADIENT = 'GRADIENT', '그라데이션'

    title = models.CharField(max_length=200, verbose_name='제목')
    subtitle = models.CharField(max_length=300, blank=True, verbose_name='부제목')
    order = models.PositiveIntegerField(default=0, verbose_name='순서')
    is_active = models.BooleanField(default=True, verbose_name='표시')
    background_type = models.CharField(
        max_length=20,
        choices=BackgroundType.choices,
        default=BackgroundType.GRADIENT,
    )
    image = models.ImageField(
        upload_to='carousel/',
        blank=True,
        null=True,
        verbose_name='배경 이미지',
    )
    gradient_css = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='그라데이션 CSS',
        help_text='예: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '캐러셀 슬라이드 (홈 인트로)'
        verbose_name_plural = '캐러셀 슬라이드 (홈 인트로)'
        ordering = ['order', 'id']

    def __str__(self):
        return self.title
