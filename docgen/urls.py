from django.urls import path
from . import views

urlpatterns = [
    # 1. Nova Home (Dashboard com Gráficos)
    path('', views.home_dashboard, name='home'),

    # 2. Catálogo (Antiga lista_templates)
    path('catalogo/', views.lista_templates, name='lista_templates'),

    # 3. Gerador de Documentos
    path('gerar/<int:template_id>/', views.gerar_documento, name='gerar_documento'),

    # 4. Histórico do Usuário
    path('meus-documentos/', views.dashboard, name='dashboard'),

    # 5. Biblioteca de Modelos
    path('biblioteca/', views.biblioteca_modelos, name='biblioteca'),

    # 6. Cadastro de Usuário (Customizado)
    path('accounts/signup/', views.SignUpView.as_view(), name='signup'),
    
    # Rota de ativação de conta (caso use a lógica de email no futuro)
    # path('activate/<uidb64>/<token>/', views.activate, name='activate'),
]