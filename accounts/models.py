# accounts: 인증/역할(app authentication & role)
from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """커스텀 사용자 모델 - 역할(role), 상태(status)"""

    class Role(models.TextChoices):
        ADMIN = 'ADMIN', '관리자'
        AGENT = 'AGENT', '에이전트'
        CUSTOMER = 'CUSTOMER', '고객'

    class Status(models.TextChoices):
        UNVERIFIED = 'UNVERIFIED', '인증전'
        ACTIVE = 'ACTIVE', '활성'
        PENDING = 'PENDING', '대기'
        SUSPENDED = 'SUSPENDED', '정지'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name='생년월일')

    class Gender(models.TextChoices):
        M = 'M', '남성'
        F = 'F', '여성'
        O = 'O', '기타'

    gender = models.CharField(
        max_length=2,
        choices=Gender.choices,
        null=True,
        blank=True,
        verbose_name='성별',
    )

    class Meta:
        verbose_name = '사용자'
        verbose_name_plural = '사용자들'

    def save(self, *args, **kwargs):
        if self.is_superuser and self.role != self.Role.ADMIN:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)
