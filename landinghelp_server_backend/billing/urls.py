from django.urls import path

from . import views

app_name = 'billing'

urlpatterns = [
    path('', views.subscription_plan, name='subscription_plan'),
    path('checkout/<int:plan_id>/', views.subscription_checkout, name='subscription_checkout'),
    path('complete/<int:plan_id>/', views.subscription_complete, name='subscription_complete'),
]
