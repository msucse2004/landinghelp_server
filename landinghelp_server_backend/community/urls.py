from django.urls import path
from . import views

app_name = 'community'

urlpatterns = [
    path('', views.region_select, name='region_select'),
    path('<slug:area_slug>/', views.board_list, name='board_list'),
    path('<slug:area_slug>/write/', views.post_write, name='post_write'),
    path('<slug:area_slug>/<int:post_id>/', views.post_detail, name='post_detail'),
]
