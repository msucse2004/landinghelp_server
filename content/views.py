from django.shortcuts import render, get_object_or_404

from .models import Content
from .permissions import can_view_content, filter_viewable_contents


def content_list(request):
    """ /content/ - public + 로그인 시 role/min_tier 필터 """
    qs = Content.objects.filter(status=Content.Status.PUBLISHED)
    # Python 레벨 필터링
    contents = filter_viewable_contents(request.user, list(qs))
    return render(request, 'content/list.html', {'contents': contents})


def content_detail(request, slug):
    """ /content/<slug>/ - 권한 없으면 403 + 업그레이드 안내 """
    content = get_object_or_404(Content, slug=slug, status=Content.Status.PUBLISHED)
    if not can_view_content(request.user, content):
        return render(
            request,
            'content/403_upgrade.html',
            {'content': content},
            status=403,
        )
    return render(request, 'content/detail.html', {'content': content})
