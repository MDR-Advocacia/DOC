from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path

from . import api_views, arquivos_views, sso_views, views, wopi_views


urlpatterns = [
    path('', views.home_dashboard, name='home'),
    path('meus-documentos/', views.dashboard, name='dashboard'),
    path('guia-modelos/', views.guia_modelos, name='guia_modelos'),
    path('catalogo/', views.lista_templates, name='lista_templates'),
    path('gerar/<int:template_id>/', views.gerar_documento, name='gerar_documento'),
    path('preview/<int:template_id>/', views.preview_documento, name='preview_documento'),
    path('minha-biblioteca/', views.minha_biblioteca, name='minha_biblioteca'),
    path('minha-biblioteca/nova-pasta/', views.criar_pasta, name='criar_pasta'),
    path('minha-biblioteca/excluir-pasta/<int:pasta_id>/', views.excluir_pasta, name='excluir_pasta'),
    path('minha-biblioteca/mover/<int:template_id>/', views.mover_para_pasta, name='mover_para_pasta'),
    path('minha-biblioteca/compartilhar/', views.compartilhar_pasta, name='compartilhar_pasta'),
    path('minha-biblioteca/parar-compartilhamento/<int:pasta_id>/', views.parar_compartilhamento, name='parar_compartilhamento'),
    path('biblioteca/', views.biblioteca_modelos, name='biblioteca'),
    path('arquivos/', arquivos_views.arquivos_lista, name='arquivos_lista'),
    path('arquivos/nova-pasta/', arquivos_views.criar_pasta_arquivo, name='criar_pasta_arquivo'),
    path('arquivos/compartilhar-pasta/', arquivos_views.compartilhar_pasta_arquivo, name='compartilhar_pasta_arquivo'),
    path('arquivos/parar-compartilhamento/<int:pasta_id>/', arquivos_views.parar_compartilhamento_pasta_arquivo, name='parar_compartilhamento_pasta_arquivo'),
    path('arquivos/excluir-pasta/<int:pasta_id>/', arquivos_views.excluir_pasta_arquivo, name='excluir_pasta_arquivo'),
    path('arquivos/<int:arquivo_id>/mover/', arquivos_views.arquivo_mover, name='arquivo_mover'),
    path('arquivos/<int:arquivo_id>/download/', arquivos_views.arquivo_download, name='arquivo_download'),
    path('arquivos/<int:arquivo_id>/excluir/', arquivos_views.arquivo_excluir, name='arquivo_excluir'),
    path('favoritar/<int:template_id>/', views.toggle_favorito, name='toggle_favorito'),
    path('biblioteca/adicionar/<int:template_id>/', views.adicionar_favorito, name='adicionar_favorito'),
    path('accounts/login/', auth_views.LoginView.as_view(extra_context={'sso_enabled': settings.SSO_ENABLED}), name='login'),
    path('accounts/sso/', sso_views.sso_login, name='sso_login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('accounts/signup/', views.SignUpView.as_view(), name='signup'),
    path('painel-usuarios/', views.gerenciar_usuarios, name='gerenciar_usuarios'),
    path('disparo-obrigacao-fazer/', views.disparar_obrigacao_fazer, name='disparar_obrigacao_fazer'),
    path('novo-modelo/', views.criar_template, name='criar_template'),
    path('novo-modelo/sugerir-ia/', views.sugerir_template_ia, name='sugerir_template_ia'),
    path('configurar/<int:template_id>/', views.configurar_template, name='configurar_template'),
    path('modelo/<int:template_id>/editar/', views.editar_template, name='editar_template'),
    path('modelo/<int:template_id>/excluir/', views.excluir_template, name='excluir_template'),
    path('modelo/<int:template_id>/restaurar/', views.restaurar_template, name='restaurar_template'),
    path('gestao-equipes/', views.gerenciar_equipes, name='gerenciar_equipes'),
    path('gestao-equipes/<int:equipe_id>/membros/', views.gerenciar_membros_equipe, name='gerenciar_membros_equipe'),
    path('equipes/editar/<int:equipe_id>/', views.editar_equipe, name='editar_equipe'),
    path('equipes/excluir/<int:equipe_id>/', views.excluir_equipe, name='excluir_equipe'),
    path('equipes/<int:equipe_pai_id>/criar-nucleo/', views.criar_nucleo_vinculado, name='criar_nucleo_vinculado'),
    path('definir-senha/', views.definir_senha_primeiro_acesso, name='definir_primeira_senha'),
    # Edição online (Collabora/WOPI). As rotas /wopi/ são chamadas pelo
    # servidor do Collabora, não pelo navegador — autenticam por token.
    path('gerar/<int:template_id>/editar/', wopi_views.iniciar_edicao, name='iniciar_edicao'),
    path('documento/<int:documento_id>/editar/', wopi_views.editar_documento, name='editar_documento'),
    path('wopi/files/<int:documento_id>', wopi_views.check_file_info, name='wopi_check_file_info'),
    # GetFile (GET) e PutFile (POST) compartilham a MESMA URL no protocolo —
    # o que muda é o método.
    path('wopi/files/<int:documento_id>/contents', wopi_views.contents, name='wopi_contents'),
    path('api/v1/biblioteca/', api_views.BibliotecaAPIView.as_view(), name='api_biblioteca'),
    path('api/v1/gerar/', api_views.GerarDocumentoAPIView.as_view(), name='api_gerar'),
]
