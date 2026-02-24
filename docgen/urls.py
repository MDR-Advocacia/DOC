from django.urls import path, include
from . import views
from . import api_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # 1. Dashboard e Home
    path('', views.home_dashboard, name='home'),
    path('meus-documentos/', views.dashboard, name='dashboard'), # Histórico do Usuário
    path('guia-modelos/', views.guia_modelos, name='guia_modelos'),

    # 2. Catálogo e Gerador
    path('catalogo/', views.lista_templates, name='lista_templates'),
    path('gerar/<int:template_id>/', views.gerar_documento, name='gerar_documento'),

    # 3. Biblioteca Pessoal (Minha Biblioteca) e Pastas
    path('minha-biblioteca/', views.minha_biblioteca, name='minha_biblioteca'),
    path('minha-biblioteca/nova-pasta/', views.criar_pasta, name='criar_pasta'),
    path('minha-biblioteca/excluir-pasta/<int:pasta_id>/', views.excluir_pasta, name='excluir_pasta'),
    path('minha-biblioteca/mover/<int:template_id>/', views.mover_para_pasta, name='mover_para_pasta'),
    
    # 4. Acervo Geral (Biblioteca do Escritório)
    path('biblioteca/', views.biblioteca_modelos, name='biblioteca'),

    # 5. Funcionalidades de Favoritos (AJAX)
    path('favoritar/<int:template_id>/', views.toggle_favorito, name='toggle_favorito'),

    # --- AUTENTICAÇÃO ---
    path('accounts/', include('django.contrib.auth.urls')), 
    path('accounts/signup/', views.SignUpView.as_view(), name='signup'),

    # --- ÁREA ADMINISTRATIVA / GESTÃO (Supervisores) ---
    path('painel-usuarios/', views.gerenciar_usuarios, name='gerenciar_usuarios'),
    path('novo-modelo/', views.criar_template, name='criar_template'),
    path('configurar/<int:template_id>/', views.configurar_template, name='configurar_template'),
    
    # GESTÃO DE EQUIPES E NÚCLEOS
    path('gestao-equipes/', views.gerenciar_equipes, name='gerenciar_equipes'),
    path('gestao-equipes/<int:equipe_id>/membros/', views.gerenciar_membros_equipe, name='gerenciar_membros_equipe'),

    # --- ROTAS DE API (Endpoints) ---
    path('api/v1/biblioteca/', api_views.BibliotecaAPIView.as_view(), name='api_biblioteca'),
    path('api/v1/gerar/', api_views.GerarDocumentoAPIView.as_view(), name='api_gerar'),

    path('minha-biblioteca/compartilhar/', views.compartilhar_pasta, name='compartilhar_pasta'),

    path('equipes/editar/<int:equipe_id>/', views.editar_equipe, name='editar_equipe'),
    path('equipes/excluir/<int:equipe_id>/', views.excluir_equipe, name='excluir_equipe'),

    path('equipes/<int:equipe_pai_id>/criar-nucleo/', views.criar_nucleo_vinculado, name='criar_nucleo_vinculado'),

    path('definir-senha/', views.definir_senha_primeiro_acesso, name='definir_primeira_senha'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)