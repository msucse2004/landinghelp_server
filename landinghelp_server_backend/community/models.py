from django.db import models
from django.conf import settings


class Region(models.Model):
    """지역 (서부/중부/동부)"""
    class Code(models.TextChoices):
        WEST = 'WEST', '서부지역'
        CENTRAL = 'CENTRAL', '중부지역'
        EAST = 'EAST', '동부지역'

    code = models.CharField(max_length=20, choices=Code.choices, unique=True)
    name = models.CharField(max_length=50)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.name


class Area(models.Model):
    """도시/지역 (Phoenix, Charlotte 등)"""
    region = models.ForeignKey(Region, on_delete=models.CASCADE, related_name='areas')
    state_code = models.CharField(max_length=5, verbose_name='주 코드')  # AZ, CA, NC
    state_name = models.CharField(max_length=50, blank=True)  # Arizona
    city_name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, allow_unicode=True)
    order = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='community/areas/', blank=True, null=True)

    class Meta:
        ordering = ['region', 'order', 'id']

    def __str__(self):
        return f"{self.state_code} {self.city_name}"

    def display_name(self):
        if self.state_name:
            return f"{self.state_code} {self.state_name} {self.city_name}"
        return f"{self.state_code} {self.city_name}"


class PostCategory(models.Model):
    """게시글 카테고리"""
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=50)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = '게시글 카테고리'
        verbose_name_plural = '게시글 카테고리'

    def __str__(self):
        return self.name


class Post(models.Model):
    """지역 게시판 글"""
    area = models.ForeignKey(Area, on_delete=models.CASCADE, related_name='posts')
    category = models.ForeignKey(PostCategory, on_delete=models.PROTECT, related_name='posts')
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_posts',
    )
    author_name = models.CharField(max_length=100, blank=True)  # 비로그인 또는 표시명
    thumbnail = models.ImageField(upload_to='community/posts/', blank=True, null=True)
    is_notice = models.BooleanField(default=False, verbose_name='공지')
    view_count = models.PositiveIntegerField(default=0)
    like_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_notice', '-created_at']

    def __str__(self):
        return self.title

    def increment_view(self):
        self.view_count += 1
        self.save(update_fields=['view_count'])


class PostComment(models.Model):
    """게시글 댓글"""
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='community_comments',
    )
    author_name = models.CharField(max_length=100, blank=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
