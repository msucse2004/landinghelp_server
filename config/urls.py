"""
URL configuration for landinghelp_server project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include, reverse_lazy
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)

from config.views import (
    home, app_entry, admin_dashboard, agent_dashboard, agent_appointment_calendar, customer_dashboard,
    settlement_services, settlement_intro, settlement_reviews, settlement_cost_estimate,
    corporate_services, corporate_ad_register,
    set_language,
    api_i18n,
)
from settlement.views import (
    settlement_quote,
    api_service_suggest,
    api_schedule_generate,
    api_agents_for_service,
    api_appointment_request,
    api_appointment_update,
    api_appointment_cancel,
    api_appointment_accept,
    api_checkout,
)
from accounts.views import (
    signup,
    check_username,
    find_username,
    find_username_done,
    member_list,
    member_delete,
    member_password_reset,
    verification_sent,
    verify_email,
)
from messaging.views import inbox as messaging_inbox

urlpatterns = [
    path('', home, name='home'),
    path('services/settlement/', settlement_services, name='settlement_services'),
    path('services/settlement/intro/', settlement_intro, name='settlement_intro'),
    path('services/settlement/quote/', settlement_quote, name='settlement_quote'),
    path('services/settlement/reviews/', settlement_reviews, name='settlement_reviews'),
    path('services/settlement/cost-estimate/', settlement_cost_estimate, name='settlement_cost_estimate'),
    path('services/corporate/', corporate_services, name='corporate_services'),
    path('services/corporate/ad/', corporate_ad_register, name='corporate_ad_register'),
    path('app/', app_entry, name='app_entry'),
    path('admin/dashboard/', admin_dashboard, name='app_admin_dashboard'),  # Django admin보다 먼저
    path('admin/', admin.site.urls),
    path('agent/dashboard/', agent_dashboard, name='app_agent_dashboard'),
    path('agent/appointments/', agent_appointment_calendar, name='app_agent_appointments'),
    path('customer/dashboard/', customer_dashboard, name='app_customer_dashboard'),
    path('content/', include('content.urls')),
    path('community/', include('community.urls')),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('find-username/', find_username, name='find_username'),
    path('find-username/done/', find_username_done, name='find_username_done'),
    path('password-reset/', PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('password-reset/done/', PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('password-reset/complete/', PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html',
    ), name='password_reset_complete'),
    path('signup/', signup, name='signup'),
    path('verification-sent/', verification_sent, name='verification_sent'),
    path('verify-email/', verify_email, name='verify_email'),
    path('members/', member_list, name='member_list'),
    path('members/<int:user_id>/delete/', member_delete, name='member_delete'),
    path('members/<int:user_id>/password-reset/', member_password_reset, name='member_password_reset'),
    path('api/check-username/', check_username, name='check_username'),
    path('api/settlement/suggest/', api_service_suggest, name='api_settlement_suggest'),
    path('api/settlement/schedule/', api_schedule_generate, name='api_settlement_schedule'),
    path('api/settlement/agents/', api_agents_for_service, name='api_settlement_agents'),
    path('api/settlement/appointment/', api_appointment_request, name='api_settlement_appointment'),
    path('api/settlement/appointment/<int:pk>/update/', api_appointment_update, name='api_settlement_appointment_update'),
    path('api/settlement/appointment/<int:pk>/cancel/', api_appointment_cancel, name='api_settlement_appointment_cancel'),
    path('api/settlement/appointment/<int:pk>/accept/', api_appointment_accept, name='api_settlement_appointment_accept'),
    path('api/settlement/checkout/', api_checkout, name='api_settlement_checkout'),
    path('messages/', messaging_inbox, name='messages_inbox'),
    path('api/messaging/', include('messaging.urls')),
    path('subscription/', include('billing.urls')),
    path('i18n/setlang/', set_language, name='set_language'),
    path('api/i18n/<str:lang>/', api_i18n, name='api_i18n'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
