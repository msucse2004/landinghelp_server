# 설문 기본 콘텐츠 시드 — ML 견적 draft 연동을 고려한 카드/문항 생성

from django.db import migrations


def seed_survey(apps, schema_editor):
    SurveySection = apps.get_model('survey', 'SurveySection')
    SurveyQuestion = apps.get_model('survey', 'SurveyQuestion')

    sections_data = [
        {
            'title': '신청자 정보',
            'description': '연락 가능한 신청자 정보를 입력해 주세요.',
            'display_order': 1,
            'is_active': True,
            'is_internal': False,
        },
        {
            'title': '입국 인원',
            'description': '미국 입국 예정인 성인·자녀 수를 알려 주세요.',
            'display_order': 2,
            'is_active': True,
            'is_internal': False,
        },
        {
            'title': '지역·현황',
            'description': '정착 예정 지역과 현재 거주 국가를 입력해 주세요.',
            'display_order': 3,
            'is_active': True,
            'is_internal': False,
        },
        {
            'title': '입국 목적·체류',
            'description': '미국 입국 목적과 체류 신분, 예상 체류 기간을 선택해 주세요.',
            'display_order': 4,
            'is_active': True,
            'is_internal': False,
        },
    ]

    questions_data = [
        # 1. 신청자 정보
        {'section_order': 1, 'order_in_section': 1, 'key': 'first_name', 'label': '이름 (First name)', 'field_type': 'text', 'required': True, 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 2, 'key': 'last_name', 'label': '성 (Last name)', 'field_type': 'text', 'required': True, 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 3, 'key': 'name_ko', 'label': '한글 이름', 'field_type': 'text', 'required': False, 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 4, 'key': 'gender', 'label': '성별', 'field_type': 'select', 'required': True, 'choices': [{'value': 'M', 'label': '남'}, {'value': 'F', 'label': '여'}], 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 5, 'key': 'phone', 'label': '휴대폰 번호', 'field_type': 'text', 'required': True, 'placeholder': '예: +1 234 567 8900', 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 6, 'key': 'email', 'label': '이메일', 'field_type': 'email', 'required': True, 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 7, 'key': 'chat_app_type', 'label': '채팅앱 종류', 'field_type': 'text', 'required': False, 'placeholder': '예: 카카오톡, WhatsApp', 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        {'section_order': 1, 'order_in_section': 8, 'key': 'chat_app_id', 'label': '채팅앱 아이디', 'field_type': 'text', 'required': False, 'placeholder': '예: kakao_id', 'quote_relevant': False, 'quote_mapping_key': '', 'quote_value_type': ''},
        # 2. 입국 인원
        {'section_order': 2, 'order_in_section': 1, 'key': 'adults_count', 'label': '총 입국 성인 수 (만 18세 이상)', 'field_type': 'number', 'required': True, 'quote_relevant': True, 'quote_mapping_key': 'household_adults', 'quote_value_type': 'number'},
        {'section_order': 2, 'order_in_section': 2, 'key': 'children_count', 'label': '총 입국 자녀 수 (만 19세 미만)', 'field_type': 'number', 'required': True, 'quote_relevant': True, 'quote_mapping_key': 'household_children', 'quote_value_type': 'number'},
        # 3. 지역·현황
        {'section_order': 3, 'order_in_section': 1, 'key': 'settlement_state', 'label': '정착하려는 주 (State)', 'field_type': 'text', 'required': True, 'placeholder': '예: California, CA', 'quote_relevant': True, 'quote_mapping_key': 'settlement_state', 'quote_value_type': 'text'},
        {'section_order': 3, 'order_in_section': 2, 'key': 'settlement_city', 'label': '정착하려는 도시 (City)', 'field_type': 'text', 'required': False, 'placeholder': '예: Los Angeles', 'quote_relevant': True, 'quote_mapping_key': 'settlement_city', 'quote_value_type': 'text'},
        {'section_order': 3, 'order_in_section': 3, 'key': 'current_country', 'label': '현재 거주 중인 국가', 'field_type': 'text', 'required': True, 'placeholder': '예: 대한민국', 'quote_relevant': True, 'quote_mapping_key': 'current_country', 'quote_value_type': 'text'},
        # 4. 입국 목적·체류
        {'section_order': 4, 'order_in_section': 1, 'key': 'entry_purpose', 'label': '미국 입국 목적', 'field_type': 'select', 'required': True,
         'choices': [
             {'value': 'immigration', 'label': '이민'},
             {'value': 'study', 'label': '학업'},
             {'value': 'exchange', 'label': '연수·방문학자'},
             {'value': 'work', 'label': '취업·주재원'},
             {'value': 'business_trip', 'label': '출장'},
             {'value': 'tourism', 'label': '관광'},
             {'value': 'business', 'label': '사업'},
             {'value': 'marriage', 'label': '결혼'},
             {'value': 'other', 'label': '기타'},
         ],
         'quote_relevant': True, 'quote_mapping_key': 'entry_purpose', 'quote_value_type': 'options'},
        {'section_order': 4, 'order_in_section': 2, 'key': 'stay_status', 'label': '미국에서의 체류 신분', 'field_type': 'select', 'required': True,
         'choices': [
             {'value': 'esta', 'label': '무비자(ESTA)'},
             {'value': 'b1b2', 'label': '방문 비자(B1, B2)'},
             {'value': 'h1b', 'label': '취업 비자(H-1B, H-1C, H-4 등)'},
             {'value': 'f1', 'label': '학생 비자(F-1 등)'},
             {'value': 'j1', 'label': '교환·방문(J-1 등)'},
             {'value': 'green_card', 'label': '영주권 등'},
             {'value': 'other', 'label': '기타'},
         ],
         'quote_relevant': True, 'quote_mapping_key': 'stay_status', 'quote_value_type': 'options'},
        {'section_order': 4, 'order_in_section': 3, 'key': 'stay_duration', 'label': '예상 미국 체류 기간', 'field_type': 'text', 'required': True, 'placeholder': '예: 3개월, 1년', 'quote_relevant': True, 'quote_mapping_key': 'stay_duration', 'quote_value_type': 'text'},
    ]

    created_sections = []
    for s in sections_data:
        sec, _ = SurveySection.objects.get_or_create(
            title=s['title'],
            defaults={
                'description': s.get('description', ''),
                'display_order': s['display_order'],
                'is_active': s.get('is_active', True),
                'is_internal': s.get('is_internal', False),
            },
        )
        created_sections.append((s['display_order'], sec))

    created_sections.sort(key=lambda x: x[0])
    order_to_section = {order: sec for order, sec in created_sections}

    for q in questions_data:
        section = order_to_section.get(q['section_order'])
        choices = q.get('choices', [])
        SurveyQuestion.objects.get_or_create(
            key=q['key'],
            defaults={
                'section': section,
                'order_in_section': q['order_in_section'],
                'order': q['order_in_section'],
                'step': q['section_order'],
                'label': q['label'],
                'field_type': q['field_type'],
                'required': q.get('required', False),
                'choices': choices,
                'placeholder': q.get('placeholder', ''),
                'help_text': q.get('help_text', ''),
                'quote_relevant': q.get('quote_relevant', False),
                'quote_mapping_key': q.get('quote_mapping_key', ''),
                'quote_value_type': q.get('quote_value_type', ''),
                'is_active': True,
            },
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('survey', '0006_survey_submission_section_request'),
    ]

    operations = [
        migrations.RunPython(seed_survey, noop),
    ]
