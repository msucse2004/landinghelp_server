# content: 권한 체크 (옵션 A)

from billing.utils import get_user_tier


def can_view_content(user, content):
    """
    user가 content를 볼 수 있는지 여부.
    - is_public + PUBLISHED: 누구나
    - 로그인 사용자: role in allowed_roles AND user_tier >= min_tier
    - 비로그인(GUEST): 'GUEST' in allowed_roles AND min_tier <= BASIC
    """
    if content.status != content.Status.PUBLISHED:
        return False
    if content.is_public:
        return True
    if not isinstance(content.allowed_roles, list):
        return False

    if not user or not user.is_authenticated:
        # 비로그인 = GUEST, tier=BASIC(1)
        return 'GUEST' in content.allowed_roles and content.min_tier <= 1

    if user.role not in content.allowed_roles:
        return False
    user_tier = get_user_tier(user)
    tier_val = getattr(user_tier, 'value', user_tier) if hasattr(user_tier, 'value') else user_tier
    return int(tier_val) >= content.min_tier


def filter_viewable_contents(user, contents):
    """
    Python 레벨 필터링: contents 중 user가 볼 수 있는 것만 반환.
    """
    result = []
    for c in contents:
        if can_view_content(user, c):
            result.append(c)
    return result
