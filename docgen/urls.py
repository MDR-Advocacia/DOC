from django.urls import path
from . import views

urlpatterns = [
    path('', views.lista_templates, name='lista_templates'),
    path('gerar/<int:template_id>/', views.gerar_documento, name='gerar_documento'),
    path('meus-documentos/', views.dashboard, name='dashboard'),
    path('biblioteca/', views.biblioteca_modelos, name='biblioteca'),
]