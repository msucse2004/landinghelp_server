from django.contrib import admin
from adminsortable2.admin import SortableAdminMixin
from .models import Content, CarouselSlide, HomeIntroSlide, SettlementCarouselSlide, CorporateCarouselSlide, AdCarouselSlide, CorporateAdRequest
from .forms import ContentAdminForm


PLACEMENT_HOME_INTRO = CarouselSlide.Placement.HOME_INTRO
PLACEMENT_SETTLEMENT = CarouselSlide.Placement.SETTLEMENT
PLACEMENT_CORPORATE = CarouselSlide.Placement.CORPORATE
PLACEMENT_AD = CarouselSlide.Placement.AD


class BaseCarouselAdmin(SortableAdminMixin, admin.ModelAdmin):
    change_list_template = 'admin/content/carouselslide/change_list.html'
    list_display = ('order_index', 'title', 'subtitle', 'link_url', 'background_type', 'is_active', 'updated_at')
    list_editable = ('is_active',)
    list_display_links = ('title',)
    list_filter = ('background_type', 'is_active')
    search_fields = ('title', 'subtitle')
    ordering = ('order', 'id')

    def order_index(self, obj):
        return obj.order + 1
    order_index.short_description = 'No.'


@admin.register(HomeIntroSlide)
class HomeIntroSlideAdmin(BaseCarouselAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(placement=PLACEMENT_HOME_INTRO)

    def save_model(self, request, obj, form, change):
        obj.placement = PLACEMENT_HOME_INTRO
        super().save_model(request, obj, form, change)


@admin.register(SettlementCarouselSlide)
class SettlementCarouselSlideAdmin(BaseCarouselAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(placement=PLACEMENT_SETTLEMENT)

    def save_model(self, request, obj, form, change):
        obj.placement = PLACEMENT_SETTLEMENT
        super().save_model(request, obj, form, change)


@admin.register(CorporateCarouselSlide)
class CorporateCarouselSlideAdmin(BaseCarouselAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(placement=PLACEMENT_CORPORATE)

    def save_model(self, request, obj, form, change):
        obj.placement = PLACEMENT_CORPORATE
        super().save_model(request, obj, form, change)


@admin.register(AdCarouselSlide)
class AdCarouselSlideAdmin(BaseCarouselAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request).filter(placement=PLACEMENT_AD)

    def save_model(self, request, obj, form, change):
        obj.placement = PLACEMENT_AD
        super().save_model(request, obj, form, change)


@admin.register(CorporateAdRequest)
class CorporateAdRequestAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'ad_title', 'contact_name', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('company_name', 'ad_title', 'contact_name', 'email')
    readonly_fields = ('created_at',)


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
