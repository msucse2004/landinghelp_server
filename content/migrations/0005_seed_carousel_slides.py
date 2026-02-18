# Data migration: 초기 캐러셀 슬라이드 생성

from django.db import migrations


def seed_slides(apps, schema_editor):
    CarouselSlide = apps.get_model('content', 'CarouselSlide')
    slides = [
        {'title': '이사가는 동네의 지역정보는?', 'subtitle': '각 지역 게시판에서 다양한 정보를 찾아보세요.', 'order': 0, 'gradient_css': 'linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)'},
        {'title': '미국 정착의 시작', 'subtitle': '랜딩헬프와 함께 새로운 삶을 준비하세요.', 'order': 1, 'gradient_css': 'linear-gradient(135deg, #0f172a 0%, #334155 100%)'},
        {'title': '정착에 필요한 정보', 'subtitle': '이사, 학교, 의료 등 지역별 실질적 정보를 제공합니다.', 'order': 2, 'gradient_css': 'linear-gradient(135deg, #1e3a5f 0%, #0ea5e9 100%)'},
        {'title': '커뮤니티와 함께', 'subtitle': '다양한 게시판에서 경험을 나누고 질문하세요.', 'order': 3, 'gradient_css': 'linear-gradient(135deg, #1e3a5f 0%, #0ea5e9 100%)'},
    ]
    for s in slides:
        CarouselSlide.objects.get_or_create(title=s['title'], defaults={**s, 'background_type': 'GRADIENT'})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0004_add_carousel_slide'),
    ]

    operations = [
        migrations.RunPython(seed_slides, noop),
    ]
