from django.urls import path
from . import views

app_name = 'ai_agent'

urlpatterns = [
    path('', views.assistant_chat, name='assistant_chat'),
    path('send/', views.assistant_send, name='assistant_send'),
]
