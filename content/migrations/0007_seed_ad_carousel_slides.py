# Data migration: 기본 광고 캐러셀 슬라이드 생성 (모든 화면 하단 노출용)

from django.db import migrations


def seed_ad_slides(apps, schema_editor):
    CarouselSlide = apps.get_model('content', 'CarouselSlide')
    AD = 'AD'
    slides = [
        {
            'title': '광고 문의',
            'subtitle': '랜딩헬프와 함께 비즈니스를 성장시키세요.',
            'order': 0,
            'placement': AD,
            'gradient_css': 'linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)',
        },
    ]
    for s in slides:
        CarouselSlide.objects.get_or_create(
            placement=AD,
            title=s['title'],
            defaults={
                **s,
                'background_type': 'GRADIENT',
                'is_active': True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('content', '0006_add_carousel_placement'),
    ]
    operations = [
        migrations.RunPython(seed_ad_slides, noop),
    ]
