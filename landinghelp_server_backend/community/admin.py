from django.contrib import admin
from .models import Region, Area, PostCategory, Post, PostComment


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order')


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    list_display = ('state_code', 'city_name', 'region', 'slug', 'order')
    list_filter = ('region',)
    prepopulated_fields = {}


@admin.register(PostCategory)
class PostCategoryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'order')


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'area', 'category', 'author_name', 'is_notice', 'view_count', 'created_at')
    list_filter = ('area', 'category', 'is_notice')
    search_fields = ('title', 'content')


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ('post', 'author_display', 'content_short', 'created_at')

    def author_display(self, obj):
        return obj.author_name or (obj.author.username if obj.author else '-')
    author_display.short_description = '작성자'

    def content_short(self, obj):
        return (obj.content[:40] + '...') if len(obj.content) > 40 else obj.content
    content_short.short_description = '내용'
