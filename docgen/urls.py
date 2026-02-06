from django.urls import path, include  # <--- 1. ADICIONE O 'include' AQUI
from . import views
from . import api_views

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

    # --- AUTENTICAÇÃO (O QUE ESTAVA FALTANDO) ---
    # Essa linha mágica cria as rotas: /accounts/login/, /accounts/logout/, etc.
    path('accounts/', include('django.contrib.auth.urls')),  # <--- 2. ESSA LINHA É OBRIGATÓRIA

    # 6. Cadastro de Usuário (Customizado)
    # Nota: Certifique-se que sua view de signup chama SignUpView mesmo, ou views.signup
    path('accounts/signup/', views.SignUpView.as_view(), name='signup'),

    # --- ROTAS DE API (Endpoints) ---
    path('api/v1/biblioteca/', api_views.BibliotecaAPIView.as_view(), name='api_biblioteca'),
    path('api/v1/gerar/', api_views.GerarDocumentoAPIView.as_view(), name='api_gerar'),
]