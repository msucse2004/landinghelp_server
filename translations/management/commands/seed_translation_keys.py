"""
코드·템플릿·DB에서 번역 키(문구)를 수집해 StaticTranslation에 키만 등록합니다.
번역문(ko, en, ...)은 키와 동일한 값으로 ko에 넣고, 나머지는 빈 값으로 둡니다.

  python manage.py seed_translation_keys
  python manage.py seed_translation_keys --dry-run  # 등록할 키만 출력
"""
from django.core.management.base import BaseCommand

# 코드/템플릿에서 사용하는 고정 문구 (DisplayKey, get_display_text, {% trans %} 등)
CODE_KEYS = [
    # settlement/models.py, forms.py, views.py
    '서비스 코드',
    '견적/스케줄 식별용 (예: DRIVERS_LICENSE). 비어있으면 id 사용',
    '항목이름',
    '카테고리',
    '필요 시간(분)',
    '예: 60 = 1시간',
    'Customer 가격',
    'Agent 가격',
    '활성',
    '서비스 항목',
    '선택 서비스',
    '이주 State',
    '도시',
    '입국/이주 예정일',
    '이름',
    '이메일',
    '서비스 일정',
    '날짜별 서비스: {"YYYY-MM-DD": ["SERVICE_CODE", ...]}',
    'Checkout 합계',
    '서비스 customer_price 합계',
    '추가 문의사항',
    'AI 추천 사용',
    '신청자',
    '견적 신청',
    '사용자',
    '{"YYYY-MM-DD": [{"code":"X","label":"Y"}, ...]}',
    '사용자 정착 플랜',
    'Agent',
    '희망 일자',
    '희망 시간대',
    '메시지',
    '연락처 이름',
    '연락처 이메일',
    '상태',
    '취소 사유',
    '취소 시 사유. 예: 사용자 취소, Agent 취소',
    '수락 독촉 알림 발송 시각',
    '24시간 미수락 시 에이전트에게 보낸 독촉 메시지 발송 시각',
    '약속 신청',
    '이주할 State',
    '예: Los Angeles',
    '예상 일정, 지역, 특별 요청사항 등을 적어주세요.',
    '서비스 선택',
    # settlement/views.py get_display_text
    '스케줄 사용자',
    '스케줄이 저장되었습니다. 예상 Checkout: %(total)s원',
    '입력값을 확인해 주세요.',
    '결제하시겠습니까?',
    '결제하기',
    '결제 처리에 실패했습니다.',
    '요청에 실패했습니다.',
    '메시지 보내기',
    '수정',
    '취소',
    '희망 시간',
    '추가 요청사항',
    '저장',
    '서비스',
    '일자',
    '신청 일시',
    '수정에 실패했습니다.',
    '이 약속을 취소하시겠습니까?',
    '취소에 실패했습니다.',
    '결재 대기',
    '결재 대기중',
    '결제를 완료하면 에이전트에게 약속이 전달됩니다.',
    '가능한 Agent',
    '로딩 중...',
    '해당 지역·서비스를 담당하는 Agent가 없습니다.',
    '평가 없음',
    '수락률',
    'Agent 목록을 불러올 수 없습니다.',
    '커버 지역',
    '제공 서비스',
    '정착 서비스를 제공합니다.',
    '전송 중...',
    '약속 신청이 완료되었습니다.',
    '이 서비스는 유료입니다. 결제를 완료하시면 에이전트에게 약속이 전달됩니다. 아래 "결제하기" 버튼을 눌러 주세요.',
    '신청에 실패했습니다.',
    '네트워크 오류가 발생했을 수 있습니다. 다시 시도해 주세요.',
    '취소됨',
    '삭제',
    '약속 취소에 실패했습니다.',
    '약속 취소 요청에 실패했습니다.',
    '스케줄 생성 전에 아래에서 서비스 카드를 클릭해 선택해 주세요.',
    '입국 예정일을 입력해 주세요.',
    '스케줄 생성 중...',
    '스케줄 생성은 스탠다드 이상 등급에서 이용 가능합니다.',
    '선택한 서비스가 입국일 기준 2주 일정으로 달력에 배치되었습니다.',
    '스케줄 생성에 실패했습니다.',
    '스케줄 요청에 실패했습니다.',
    '필요한 서비스를 입력해 주세요.',
    '추천 중...',
    'AI 서비스 추천은 스탠다드 이상 등급에서 이용 가능합니다.',
    '추천 서비스가 선택되었습니다. 달력에 드래그하거나 "2주일 스캐쥴 짜줘"로 자동 배치하세요.',
    '관련 서비스를 찾지 못했습니다. 직접 선택해 주세요.',
    '추천 요청에 실패했습니다.',
    '저장 중...',
    '저장되었습니다.',
    '저장에 실패했습니다.',
    '확인',
    '닫기',
    '원',
    '무료',
    'Agent 선택 필요',
    '합계',
    '달력에서 서비스 카드를 클릭해 Agent를 선택한 항목만 과금되며 여기에 표시됩니다.',
    '달력에 서비스를 드래그하고 Agent를 선택하면 결제할 항목이 여기에 표시됩니다. (이미 결제한 항목은 표시되지 않습니다.)',
    '약속 상세',
    '실행',
    '년',
    '월',
    '1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월',
    '이전',
    '다음',
    '일',
    '화',
    '수',
    '목',
    '금',
    '토',
    '요일_일',
    '요일_월',
    '요일_화',
    '요일_수',
    '요일_목',
    '요일_금',
    '요일_토',
    '예: 오전 10시',
    '예: 오전 10시, 오후 2시',
    # accounts/forms.py, models.py, admin.py
    'KR 한국어',
    'EN English',
    'ES Español',
    'ZH 中文(简体)',
    'ZH 中文(繁體)',
    'VI Tiếng Việt',
    '가입 시 사용한 이메일',
    '새 비밀번호',
    '새 비밀번호 확인',
    '비밀번호가 일치하지 않습니다.',
    '고객 (Customer)',
    '에이전트 (Agent)',
    '계정 유형',
    '생년월일',
    '연도-월-일',
    '선택하세요',
    '남성',
    '여성',
    '기타',
    '성별',
    '선호 언어',
    '평가자 (Customer)',
    '평가 대상 (Agent)',
    '별점',
    '1~5점',
    '한줄평',
    '에이전트 별점',
    '에이전트 서비스 (가입 시 선택)',
    '에이전트 가입 시 선택한 SettlementService ID 목록',
    '커버 주(State)',
    '에이전트가 커버하는 주 코드 목록 (예: NC, CA, TX)',
    '커버 도시',
    '에이전트가 커버하는 도시 Area ID 목록',
    '커버 도시 (주별)',
    '주별 도시 ID: {"NC": [1,2,3], "CA": [10,11]}',
    '프로필 사진',
    'Accept rate (수락률)',
    '에이전트 전체 약속 수락률. 예: 0.85 = 85%. 비워두면 서비스별 통계에서 계산해 표시.',
    '사용자들',
    '에이전트별 별점',
    '고객 평가',
    '고객 평가 내역',
    # content/models.py
    '접근 허용 역할 (GUEST=비로그인, CUSTOMER, AGENT, ADMIN)',
    '컨텐츠',
    '노출 위치',
    '제목',
    '부제목',
    '링크 URL',
    '광고 등 클릭 시 이동할 URL',
    '정렬',
    '표시',
    '배경 이미지',
    '그라데이션 CSS',
    '예: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%)',
    '캐러셀 슬라이드',
    '회사/업체명',
    '담당자명',
    '연락처',
    '광고 제목',
    '광고 부제목',
    '추가 요청사항',
    '광고 등록 신청',
    '캐러셀 (홈인트로)',
    '캐러셀 (정착서비스)',
    '캐러셀 (기업서비스)',
    '캐러셀 (광고)',
    # templates
    '카테고리',
    '수정일',
    '목록으로',
    '회원가입',
    '클릭하여 선택 해제',
    '확인 중...',
    '프로필에 표시될 사진을 등록하세요.',
    '사진 선택',
    '서비스 선택 (복수 선택)',
    '제공할 서비스를 선택하세요.',
    '등록된 서비스가 없습니다.',
    '커버 도시 (복수 선택)',
    '주(State)를 선택한 후 해당 주의 도시를 선택하세요. 여러 주에서 도시를 선택할 수 있습니다.',
    '선택된 도시',
    '주(State) 선택',
    '주를 선택하세요',
    '등록된 도시가 없습니다.',
    '가입하기',
    '정착 플랜',
    '현재 등급',
    '기본 메뉴얼을 참고하여 직접 진행할 수 있는 서비스를 제공합니다.',
    '기본 메뉴얼을 보고 따라 할 수 있는 서비스를 제공합니다.',
    '정착 서비스 소개',
    '에서 메뉴얼을 확인하세요.',
    'AI 추천 및 에이전트 도움을 원하시면 상위 요금제로 업그레이드하세요.',
    '무료 Agent 서비스',
    '모든 항목에 에이전트가 도움을 드립니다.',
    '필요 시 에이전트의 도움을 받을 수 있으며, 패키지 또는 단일 항목으로 계약 가능합니다.',
    '예상 Checkout 합계',
    '서비스별 Customer 가격 기준',
    '이주 정보',
    'AI 서비스 추천 / 스케줄 생성',
    '서비스 추천: "이사 직후 운전면허, 은행 필요해요" — 스케줄 생성: "2주일 동안 아래 선택된 항목들의 스캐쥴 짜줘" (위 이주 예정일 입력 후)',
    '카드를 클릭해 선택/해제하고, 드래그하여 달력에 놓으세요. "2주일 스캐쥴 짜줘" 입력 시 선택된 항목이 자동 배치됩니다.',
    '일정 달력',
    '카드를 날짜 칸에 드래그하여 배치하세요. 서비스 카드를 클릭해 Agent를 선택한 뒤 저장하면 예상 결제 금액이 홈·대시보드에 표시됩니다. 월/연도를 변경할 수 있습니다.',
    # settlement 서비스 카드 카테고리 (SettlementService.Category)
    '주거/임대',
    '교통/차량',
    '생활편의',
    '의료/교육',
    '행정/문서',
    '기타',
    'Agent 신청 항목 · 과금',
    '달력에서 서비스 카드를 클릭해 Agent를 선택한 항목만 과금되며 여기에 표시됩니다.',
    '추가 요청사항을 적어주세요.',
    '필요한 서비스를 한글로 입력하거나, 2주일 스캐쥴 짜줘 입력',
    '컨텐츠 목록',
    '표시할 컨텐츠가 없습니다.',
    '이메일 설정 경고',
    'EMAIL_HOST_USER, EMAIL_HOST_PASSWORD 환경변수가 설정되지 않았습니다.',
    '이메일 발송이 동작하지 않습니다.',
    '이메일 설정 경고: EMAIL_HOST_USER, EMAIL_HOST_PASSWORD 환경변수가 설정되지 않았습니다. 이메일 발송이 동작하지 않습니다.',
    '플랜',
    '메시지 함',
    '읽지 않은 메시지',
    '건',
    '로그아웃',
    '로그인',
    '정착서비스',
    '미국 이민·정착 관련 서비스를 제공합니다.',
    '정착 서비스 소개',
    '미국 이민·정착을 위한 맞춤 서비스를 소개합니다.',
    '(준비 중)',
    '정착서비스를 이용하신 고객님들의 후기입니다.',
    '직접 정착하실 경우 예상 비용을 계산해 보세요.',
    '1. 정착 서비스 소개',
    '2. 정착 플랜',
    '3. 고객 후기',
    '4. 셀프 정착 비용 예상',
    '고객 후기',
    '셀프 정착 비용 예상',
    '고객예약 달력',
    '기업서비스',
    '지역 게시판',
    '관리',
    '기업 광고',
    '번째 슬라이드',
    '새 메시지가 도착했습니다',
    '메시지함으로 이동',
    '기본 정보부터 시작하세요',
    '소개 캐러셀',
    '고객 대시보드',
    '님, 환영합니다',
    '고객 계정입니다.',
    '내 플랜:',
    '무료 Agent 서비스:',
    '수락 대기 중인 예약',
    '내 정착 일정',
    '원',
    '정착 플랜 만들기',
    '컨텐츠 보기',
    '예약 수정',
    '예: 오전 10시',
    '에이전트에게 전달할 메시지',
    '내 정착 플랜',
    '예상 Checkout',
    '입국 예정',
    '저장된 일정이 있습니다',
    '정착 플랜 수정',
    '아이디와 비밀번호를 확인해주세요.',
    '아이디',
    '비밀번호',
    '비밀번호 확인',
    '아이디 찾기',
    '비밀번호 찾기',
]


def collect_keys_from_db():
    """DB에 저장된 캐러셀/콘텐츠/서비스/광고 문구 수집."""
    keys = set()
    try:
        from content.models import CarouselSlide, Content, CorporateAdRequest
        for obj in CarouselSlide.objects.all().only('title', 'subtitle'):
            if obj.title and obj.title.strip():
                keys.add(obj.title.strip())
            if obj.subtitle and obj.subtitle.strip():
                keys.add(obj.subtitle.strip())
        for obj in Content.objects.all().only('title', 'summary'):
            if obj.title and obj.title.strip():
                keys.add(obj.title.strip())
            if obj.summary and obj.summary.strip():
                keys.add(obj.summary.strip())
        for obj in CorporateAdRequest.objects.all().only('ad_title', 'ad_subtitle'):
            if obj.ad_title and obj.ad_title.strip():
                keys.add(obj.ad_title.strip())
            if obj.ad_subtitle and obj.ad_subtitle.strip():
                keys.add(obj.ad_subtitle.strip())
    except Exception:
        pass
    try:
        from settlement.models import SettlementService
        for obj in SettlementService.objects.all().only('name'):
            if obj.name and str(obj.name).strip():
                keys.add(str(obj.name).strip())
    except Exception:
        pass
    return keys


class Command(BaseCommand):
    help = '코드·DB에서 번역 키를 수집해 StaticTranslation에 키만 등록 (ko=키, 나머지 빈 값)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='등록하지 않고 등록될 키 목록만 출력',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        from translations.models import StaticTranslation, LANG_COLUMNS

        all_keys = set()
        for k in CODE_KEYS:
            s = (k or '').strip()
            if s:
                all_keys.add(s)
        for k in collect_keys_from_db():
            if k:
                all_keys.add(k)

        all_keys = sorted(all_keys)
        if dry_run:
            self.stdout.write(f'등록될 키 수: {len(all_keys)}')
            for k in all_keys:
                self.stdout.write(f'  {k}')
            return

        created = 0
        for key in all_keys:
            _, created_ = StaticTranslation.objects.get_or_create(
                key=key,
                defaults={
                    'ko': key,
                    'en': '',
                    'es': '',
                    'zh_hans': '',
                    'zh_hant': '',
                    'vi': '',
                },
            )
            if created_:
                created += 1

        # 날짜 입력 placeholder "연도-월-일" 기본 번역 (브라우저 힌트 대신 우리가 표시)
        for row in StaticTranslation.objects.filter(key='연도-월-일'):
            if not (row.en and str(row.en).strip()):
                row.en = 'YYYY-MM-DD'
            if not (row.es and str(row.es).strip()):
                row.es = 'AAAA-MM-DD'
            if not (row.zh_hans and str(row.zh_hans).strip()):
                row.zh_hans = 'YYYY-MM-DD'
            if not (row.zh_hant and str(row.zh_hant).strip()):
                row.zh_hant = 'YYYY-MM-DD'
            if not (row.vi and str(row.vi).strip()):
                row.vi = 'YYYY-MM-DD'
            row.save()
            break

        self.stdout.write(self.style.SUCCESS(f'키 {len(all_keys)}개 중 새로 등록: {created}개'))
        try:
            from translations.utils import invalidate_cache
            invalidate_cache()
            self.stdout.write('고정 번역 캐시를 초기화했습니다.')
        except Exception:
            pass
