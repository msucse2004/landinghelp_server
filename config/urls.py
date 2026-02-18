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

from config.views import home, app_entry, admin_dashboard, agent_dashboard, customer_dashboard
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

urlpatterns = [
    path('', home, name='home'),
    path('app/', app_entry, name='app_entry'),
    path('admin/dashboard/', admin_dashboard, name='app_admin_dashboard'),  # Django admin보다 먼저
    path('admin/', admin.site.urls),
    path('agent/dashboard/', agent_dashboard, name='app_agent_dashboard'),
    path('customer/dashboard/', customer_dashboard, name='app_customer_dashboard'),
    path('content/', include('content.urls')),
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
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
