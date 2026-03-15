# 서비스 진행 방식 카드: 선택 서비스 리스트업 + 진행 방식 문항 (직접 검색 / AI / Agent)

from django.db import migrations


def add_service_delivery_section(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    section, _ = SurveySection.objects.get_or_create(
        title='서비스 진행 방식',
        defaults={
            'description': '선택하신 서비스를 어떻게 진행하고 싶은지 알려 주세요.',
            'display_order': 7,
            'is_active': True,
            'is_internal': False,
        },
    )

    SurveyQuestion.objects.get_or_create(
        key='service_delivery_preference',
        defaults={
            'section': section,
            'order_in_section': 1,
            'order': 1,
            'step': 7,
            'label': '서비스를 어떻게 진행하고 싶으신가요?',
            'field_type': 'radio',
            'required': False,
            'choices': [
                {'value': 'direct_search', 'label': '직접 검색 — 스스로 정보를 검색하고 준비할게요'},
                {'value': 'ai_service', 'label': 'AI 서비스 — AI가 안내·추천해 주면 좋겠어요'},
                {'value': 'agent_direct', 'label': 'Agent 직접 도움 — 에이전트가 직접 대면·대행해 주면 좋겠어요'},
            ],
            'placeholder': '',
            'help_text': '선택하신 서비스 전체에 적용됩니다. 필요하면 나중에 서비스별로 다르게 설정할 수 있어요.',
            'quote_relevant': True,
            'quote_mapping_key': 'service_delivery_preference',
            'quote_value_type': 'options',
            'is_active': True,
        },
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0011_add_airport_pickup_detail_questions'),
    ]

    operations = [
        migrations.RunPython(add_service_delivery_section, noop),
    ]
