from django.urls import path, include
from . import views
from . import api_views
from django.conf import settings
from django.conf.urls.static import static

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

    # --- AUTENTICAÇÃO ---
    path('accounts/', include('django.contrib.auth.urls')), 
    path('accounts/signup/', views.SignUpView.as_view(), name='signup'),

    # --- ROTAS ADMINISTRATIVAS (Supervisores) ---
    path('novo-modelo/', views.criar_template, name='criar_template'),
    path('configurar/<int:template_id>/', views.configurar_template, name='configurar_template'),

    # --- ROTAS DE API (Endpoints) ---
    path('api/v1/biblioteca/', api_views.BibliotecaAPIView.as_view(), name='api_biblioteca'),
    path('api/v1/gerar/', api_views.GerarDocumentoAPIView.as_view(), name='api_gerar'),

    path('guia-modelos/', views.guia_modelos, name='guia_modelos'),

    # --- ROTAS ADMINISTRATIVAS (Supervisores) ---
    path('novo-modelo/', views.criar_template, name='criar_template'),
    path('configurar/<int:template_id>/', views.configurar_template, name='configurar_template'),
    
    # NOVA ROTA: Painel de Usuários
    path('painel-usuarios/', views.gerenciar_usuarios, name='gerenciar_usuarios'),

    # 4. Histórico do Usuário
    path('meus-documentos/', views.dashboard, name='dashboard'),

    # 5. Biblioteca de Modelos (agora Acervo)
    path('biblioteca/', views.biblioteca_modelos, name='biblioteca'),

    # NOVA ROTA: Minha Biblioteca (Favoritos)
    path('minha-biblioteca/', views.minha_biblioteca, name='minha_biblioteca'),
    path('minha-biblioteca/nova-pasta/', views.criar_pasta, name='criar_pasta'),
    path('minha-biblioteca/excluir-pasta/<int:pasta_id>/', views.excluir_pasta, name='excluir_pasta'),
    path('minha-biblioteca/mover/<int:template_id>/', views.mover_para_pasta, name='mover_para_pasta'),

    # NOVA ROTA: Favoritar via JavaScript (AJAX)
    path('favoritar/<int:template_id>/', views.toggle_favorito, name='toggle_favorito'),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)