from django.urls import path
from . import views

app_name = 'messaging'

urlpatterns = [
    path('conversations/', views.api_conversation_list, name='conversation_list'),
    path('conversations/<int:conversation_id>/', views.api_conversation_detail, name='conversation_detail'),
    path('conversations/<int:conversation_id>/messages/', views.api_conversation_messages, name='conversation_messages'),
    path('conversations/<int:conversation_id>/read/', views.api_mark_read, name='mark_read'),
    path('unread-count/', views.api_unread_count, name='unread_count'),
    path('dismiss-login-popup/', views.api_dismiss_login_popup, name='dismiss_login_popup'),
    path('notices/', views.api_create_notice, name='create_notice'),
]
