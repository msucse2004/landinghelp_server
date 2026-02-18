from django.contrib import admin
from adminsortable2.admin import SortableAdminMixin
from .models import Content, CarouselSlide
from .forms import ContentAdminForm


@admin.register(CarouselSlide)
class CarouselSlideAdmin(SortableAdminMixin, admin.ModelAdmin):
    change_list_template = 'admin/content/carouselslide/change_list.html'
    list_display = ('order_index', 'title', 'subtitle', 'background_type', 'is_active', 'updated_at')

    def order_index(self, obj):
        """1-based 순서 표시 (드래그 후 JS로 자동 갱신)"""
        return obj.order + 1

    order_index.short_description = 'No.'
    list_editable = ('is_active',)
    list_display_links = ('title',)
    list_filter = ('background_type', 'is_active')
    search_fields = ('title', 'subtitle')
    ordering = ('order', 'id')


@admin.register(Content)
class ContentAdmin(admin.ModelAdmin):
    form = ContentAdminForm
    list_display = ('title', 'slug', 'category', 'status', 'is_public', 'min_tier', 'updated_at')
    list_filter = ('status', 'is_public', 'min_tier')
    search_fields = ('title', 'slug', 'category')
    prepopulated_fields = {'slug': ('title',)}
    raw_id_fields = ('created_by',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)
