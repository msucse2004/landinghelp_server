from django.shortcuts import render, get_object_or_404

from .models import Content
from .permissions import can_view_content, filter_viewable_contents


def content_list(request):
    """ /content/ - public + 로그인 시 role/min_tier 필터. 언어별 표시용 _display 보강."""
    qs = Content.objects.filter(status=Content.Status.PUBLISHED)
    contents = filter_viewable_contents(request.user, list(qs))
    try:
        from translations.utils import enrich_objects_for_display
        enrich_objects_for_display(contents, ['title', 'summary'])
    except Exception:
        for c in contents:
            c.title_display = getattr(c, 'title', '') or ''
            c.summary_display = getattr(c, 'summary', '') or ''
    return render(request, 'content/list.html', {'contents': contents})


def content_detail(request, slug):
    """ /content/<slug>/ - 권한 없으면 403 + 업그레이드 안내. 언어별 표시용 _display 보강."""
    content = get_object_or_404(Content, slug=slug, status=Content.Status.PUBLISHED)
    try:
        from translations.utils import enrich_objects_for_display
        enrich_objects_for_display([content], ['title', 'summary'])
    except Exception:
        content.title_display = getattr(content, 'title', '') or ''
        content.summary_display = getattr(content, 'summary', '') or ''
    if not can_view_content(request.user, content):
        return render(
            request,
            'content/403_upgrade.html',
            {'content': content},
            status=403,
        )
    return render(request, 'content/detail.html', {'content': content})
