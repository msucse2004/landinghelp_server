# billing: 템플릿 컨텍스트 프로세서 (플랜 표시는 항상 DB 조회 후 설정 언어로 표시)

def user_plan_info(request):
    """
    user_id, user_plan_display, plan_label 제공.
    user_plan_display: get_user_grade_display() 단일 경로 — DB(구독/플랜) 조회 후 번역 DB로 언어별 문구 반환.
    plan_label: 번역 DB에서 '플랜' 키로 설정 언어 문구 조회.
    """
    from translations.utils import get_display_text, get_request_language
    from .utils import get_user_grade_display
    lang = get_request_language(request)
    if not request.user.is_authenticated:
        return {
            'user_id': None,
            'user_plan_display': None,
            'plan_label': get_display_text('플랜', lang),
        }
    return {
        'user_id': request.user.username,
        'user_plan_display': get_user_grade_display(request.user, lang),
        'plan_label': get_display_text('플랜', lang),
    }
