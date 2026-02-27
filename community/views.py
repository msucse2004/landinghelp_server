from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count

from .models import Region, Area, Post, PostCategory


def region_select(request):
    """지역 선택 페이지 (서부/중부/동부 → 도시 카드)"""
    regions = Region.objects.prefetch_related('areas').order_by('order')
    return render(request, 'community/region_select.html', {
        'regions': regions,
    })


def board_list(request, area_slug):
    """지역 게시판 목록"""
    area = get_object_or_404(Area, slug=area_slug)
    category_slug = request.GET.get('cat', '')
    posts = Post.objects.filter(area=area).select_related('category', 'author').annotate(
        comment_count=Count('comments')
    )

    if category_slug:
        cat = PostCategory.objects.filter(code=category_slug).first()
        if cat:
            posts = posts.filter(category=cat)

    paginator = Paginator(posts, 20)
    page = request.GET.get('page', 1)
    page_obj = paginator.get_page(page)

    categories = PostCategory.objects.order_by('order')
    return render(request, 'community/board_list.html', {
        'area': area,
        'categories': categories,
        'current_category': category_slug,
        'page_obj': page_obj,
    })


def post_detail(request, area_slug, post_id):
    """게시글 상세"""
    area = get_object_or_404(Area, slug=area_slug)
    post = get_object_or_404(Post, area=area, pk=post_id)
    post.increment_view()
    comments = post.comments.select_related('author').order_by('created_at')
    return render(request, 'community/post_detail.html', {
        'area': area,
        'post': post,
        'comments': comments,
    })


@login_required
def post_write(request, area_slug):
    """글쓰기"""
    area = get_object_or_404(Area, slug=area_slug)
    if request.method == 'POST':
        from .forms import PostForm
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.area = area
            post.author = request.user
            post.author_name = request.user.username
            post.save()
            messages.success(request, '글이 등록되었습니다.')
            return redirect('community:post_detail', area_slug=area.slug, post_id=post.pk)
    else:
        from .forms import PostForm
        form = PostForm()
    return render(request, 'community/post_write.html', {
        'area': area,
        'form': form,
    })
