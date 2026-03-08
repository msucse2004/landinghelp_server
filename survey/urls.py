from django.urls import path
from . import views

app_name = 'survey'
urlpatterns = [
    path('', views.survey_start, name='survey_start'),
    path('step/<int:step>/', views.survey_step, name='survey_step'),
    path('step/<int:step>/save/', views.survey_step_save, name='survey_step_save'),
    path('step/<int:step>/agent-selection-fragment/', views.survey_agent_selection_fragment, name='survey_agent_selection_fragment'),
    path('submit/', views.survey_submit, name='survey_submit'),
    path('thankyou/', views.survey_thankyou, name='survey_thankyou'),
]
