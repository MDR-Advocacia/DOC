import json
import secrets
import string
from datetime import datetime

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import generic

from .forms import (
    COLUNAS_OBRIGATORIAS,
    COLUNAS_OBRIGATORIAS_POR_TIPO,
    COLUNAS_OPCIONAIS,
    ROTAS_EMAIL_EXIBICAO,
    DisparoObrigacaoFazerForm,
)
from .folder_permissions import (
    accessible_folders_queryset,
    apply_folder_permissions,
    copy_folder_permissions,
    editable_folders_queryset,
    normalize_access_level,
    require_folder_editor,
)
from .models import (
    Area,
    Categoria,
    DocumentoGerado,
    Equipe,
    PastaPersonalizada,
    Setor,
    Template,
    TemplateFavorito,
)
from .utils import (
    carregar_campos_template,
    enviar_lote_obrigacao_fazer,
    extrair_tags_do_docx,
    renderizar_template_docx,
)


def _team_memberships_for_user(user):
    if user.is_staff or user.is_superuser:
        return Equipe.objects.all()
    return Equipe.objects.filter(Q(membros=user) | Q(supervisores=user)).distinct()


def _manageable_team_ids(user):
    if user.is_staff or user.is_superuser:
        return set(Equipe.objects.values_list('id', flat=True))

    direct_ids = set(Equipe.objects.filter(supervisores=user).values_list('id', flat=True))
    manageable_ids = set(direct_ids)
    pending_ids = list(direct_ids)

    while pending_ids:
        current_id = pending_ids.pop()
        child_ids = list(Equipe.objects.filter(equipe_pai_id=current_id).values_list('id', flat=True))
        for child_id in child_ids:
            if child_id not in manageable_ids:
                manageable_ids.add(child_id)
                pending_ids.append(child_id)

    return manageable_ids


def _visible_team_ids(user, manageable_ids):
    if user.is_staff or user.is_superuser:
        return set(Equipe.objects.values_list('id', flat=True))

    equipes = {
        equipe.id: equipe
        for equipe in Equipe.objects.select_related('equipe_pai').all()
    }
    visible_ids = set(manageable_ids)

    for equipe_id in list(manageable_ids):
        equipe = equipes.get(equipe_id)
        while equipe and equipe.equipe_pai_id:
            visible_ids.add(equipe.equipe_pai_id)
            equipe = equipes.get(equipe.equipe_pai_id)

    return visible_ids


def _require_equipe_manager(user, equipe, manageable_ids=None):
    manageable_ids = manageable_ids if manageable_ids is not None else _manageable_team_ids(user)
    if user.is_staff or user.is_superuser or equipe.id in manageable_ids:
        return
    raise PermissionDenied("Voce nao tem permissao para gerenciar esta equipe.")


def _accessible_folders_queryset(user):
    return accessible_folders_queryset(user, PastaPersonalizada.ESCOPO_BIBLIOTECA)


def _editable_folders_queryset(user):
    return editable_folders_queryset(user, PastaPersonalizada.ESCOPO_BIBLIOTECA)


def _require_folder_editor(user, pasta):
    require_folder_editor(user, pasta)


def _require_staff_user(user):
    if user.is_staff or user.is_superuser:
        return
    raise PermissionDenied("Apenas perfis administrativos podem acessar esta area.")


def _apply_folder_permissions(pasta, nivel_acesso, equipes=None, usuarios=None):
    apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios)


def _ordered_unique_favorites(favoritos, user):
    favoritos_ordenados = sorted(
        favoritos,
        key=lambda favorito: (
            favorito.template.titulo.lower(),
            0 if favorito.usuario_id == user.id else 1,
            favorito.usuario.username.lower(),
        ),
    )

    favoritos_unicos = []
    templates_vistos = set()
    for favorito in favoritos_ordenados:
        if favorito.template_id in templates_vistos:
            continue
        templates_vistos.add(favorito.template_id)
        favoritos_unicos.append(favorito)

    return favoritos_unicos


def _nome_arquivo_gerado(titulo_template):
    nome_base = titulo_template.strip().replace(' ', '_') or "documento"
    return f"{nome_base}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"


@login_required
@staff_member_required
def criar_template(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        setor_id = request.POST.get('setor')
        area_id = request.POST.get('area')
        categoria_id = request.POST.get('categoria')
        arquivo = request.FILES.get('arquivo')

        if not arquivo or not titulo or not setor_id:
            messages.error(request, "Preencha os campos obrigatorios e envie um arquivo.")
        else:
            try:
                template = Template.objects.create(
                    titulo=titulo,
                    descricao=descricao,
                    setor_id=setor_id,
                    area_id=area_id or None,
                    categoria_id=categoria_id or None,
                    arquivo_template=arquivo,
                    ativo=True,
                )
                messages.success(request, "Arquivo enviado. Agora configure os campos do modelo.")
                return redirect('configurar_template', template_id=template.id)
            except Exception as exc:
                messages.error(request, f"Erro ao salvar o modelo: {exc}")

    return render(
        request,
        'docgen/novo_template.html',
        {
            'setores': Setor.objects.all().order_by('nome'),
            'areas': Area.objects.all().order_by('nome'),
            'categorias': Categoria.objects.all().order_by('nome'),
        },
    )


@login_required
@staff_member_required
def configurar_template(request, template_id):
    template = get_object_or_404(Template, pk=template_id)
    tags_encontradas = extrair_tags_do_docx(template.arquivo_template.path)

    configuracao_atual = template.configuracao_campos or []
    configuracao_por_tag = {item['tag']: item for item in configuracao_atual}

    if request.method == 'POST':
        nova_configuracao = []
        for tag in tags_encontradas:
            nova_configuracao.append(
                {
                    'tag': tag,
                    'label': request.POST.get(f'label_{tag}') or tag.replace('_', ' ').title(),
                    'tipo': request.POST.get(f'tipo_{tag}', 'text'),
                    'dependencia': request.POST.get(f'dependencia_{tag}', ''),
                    'opcoes': request.POST.get(f'opcoes_{tag}', ''),
                }
            )

        template.configuracao_campos = nova_configuracao
        template.save(update_fields=['configuracao_campos'])
        messages.success(request, "Configuracao salva com sucesso.")
        return redirect('lista_templates')

    campos = []
    for tag in tags_encontradas:
        dados = configuracao_por_tag.get(tag, {})
        campos.append(
            {
                'tag': tag,
                'label': dados.get('label', tag.replace('_', ' ').title()),
                'tipo': dados.get('tipo', 'text'),
                'dependencia': dados.get('dependencia', ''),
                'opcoes': dados.get('opcoes', ''),
            }
        )

    return render(
        request,
        'docgen/configurar_template.html',
        {
            'template': template,
            'campos': campos,
            'todas_tags': tags_encontradas,
        },
    )


@login_required
def home_dashboard(request):
    total_docs = DocumentoGerado.objects.count()
    total_templates = Template.objects.filter(ativo=True).count()

    docs_por_setor = (
        DocumentoGerado.objects.values('template__setor__nome')
        .annotate(qtd=Count('id'))
        .order_by('-qtd')
    )
    docs_por_mes = (
        DocumentoGerado.objects.annotate(mes=TruncMonth('data_geracao'))
        .values('mes')
        .annotate(qtd=Count('id'))
        .order_by('mes')
    )

    return render(
        request,
        'docgen/home.html',
        {
            'total_docs': total_docs,
            'total_templates': total_templates,
            'labels_setor': [item['template__setor__nome'] for item in docs_por_setor],
            'data_setor': [item['qtd'] for item in docs_por_setor],
            'labels_mes': [item['mes'].strftime('%B/%Y') for item in docs_por_mes],
            'data_mes': [item['qtd'] for item in docs_por_mes],
        },
    )


@login_required
def gerar_documento(request, template_id):
    template = get_object_or_404(Template, pk=template_id, ativo=True)
    campos = carregar_campos_template(template)

    if request.method == 'POST':
        try:
            conteudo_docx, dados_log, campos = renderizar_template_docx(
                template,
                dados=request.POST,
                arquivos=request.FILES,
            )
            nome_arquivo = _nome_arquivo_gerado(template.titulo)

            documento = DocumentoGerado.objects.create(
                usuario=request.user,
                template=template,
                dados_inputados=dados_log,
            )
            documento.arquivo_final.save(nome_arquivo, ContentFile(conteudo_docx), save=True)

            response = HttpResponse(
                conteudo_docx,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            )
            response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            return response
        except Exception as exc:
            messages.error(request, f"Erro ao gerar o documento: {exc}")
            return redirect('lista_templates')

    return render(request, 'docgen/formulario.html', {'template': template, 'campos': campos})


@login_required
def dashboard(request):
    if request.user.is_staff or request.user.is_superuser:
        historico = DocumentoGerado.objects.select_related('template', 'usuario').order_by('-data_geracao')
    else:
        historico = (
            DocumentoGerado.objects.filter(usuario=request.user)
            .select_related('template', 'usuario')
            .order_by('-data_geracao')
        )

    paginator = Paginator(historico, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'docgen/dashboard.html', {'historico': page_obj, 'page_obj': page_obj})


@login_required
def disparar_obrigacao_fazer(request):
    _require_staff_user(request.user)

    if request.method == 'POST':
        form = DisparoObrigacaoFazerForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                enviados, falhas = enviar_lote_obrigacao_fazer(
                    pedidos=form.cleaned_data['pedidos'],
                    solicitante=request.user,
                )
            except Exception as exc:
                messages.error(request, f"Nao foi possivel concluir o disparo do lote: {exc}")
            else:
                if enviados and not falhas:
                    messages.success(request, f"{len(enviados)} email(s) enviados com sucesso.")
                elif enviados and falhas:
                    messages.warning(
                        request,
                        f"{len(enviados)} email(s) enviados e {len(falhas)} falha(s) registradas.",
                    )
                else:
                    messages.error(request, "Nenhum email foi enviado.")

                if falhas:
                    resumo_falhas = "; ".join(
                        f"{item['identificador']} (linha {item.get('linha', '?')}): {item['erro']}"
                        for item in falhas[:3]
                    )
                    if len(falhas) > 3:
                        resumo_falhas += "; ..."
                    messages.error(request, f"Falhas no lote: {resumo_falhas}")

                return redirect('disparar_obrigacao_fazer')
    else:
        form = DisparoObrigacaoFazerForm()

    return render(
        request,
        'docgen/disparo_obrigacao_fazer.html',
        {
            'form': form,
            'colunas_obrigatorias': COLUNAS_OBRIGATORIAS,
            'colunas_obrigatorias_por_tipo': COLUNAS_OBRIGATORIAS_POR_TIPO,
            'colunas_opcionais': COLUNAS_OPCIONAIS,
            'rotas_email': ROTAS_EMAIL_EXIBICAO,
        },
    )


@login_required
def biblioteca_modelos(request):
    templates = Template.objects.filter(ativo=True).select_related('setor', 'area', 'categoria')

    busca = request.GET.get('q')
    setor_id = request.GET.get('setor')
    area_id = request.GET.get('area')
    categoria_id = request.GET.get('categoria')

    if busca:
        templates = templates.filter(Q(titulo__icontains=busca) | Q(descricao__icontains=busca))
    if setor_id and setor_id != 'todos':
        templates = templates.filter(setor_id=setor_id)
    if area_id and area_id != 'todos':
        templates = templates.filter(area_id=area_id)
    if categoria_id and categoria_id != 'todos':
        templates = templates.filter(categoria_id=categoria_id)

    templates = templates.order_by('setor__nome', 'area__nome', 'titulo')
    paginator = Paginator(templates, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'docgen/biblioteca.html',
        {
            'templates': page_obj,
            'page_obj': page_obj,
            'setores': Setor.objects.all().order_by('nome'),
            'areas': Area.objects.all().order_by('nome'),
            'categorias': Categoria.objects.all().order_by('nome'),
            'filtros_atuais': request.GET,
        },
    )


class SignUpView(generic.View):
    template_name = 'registration/signup.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        email = request.POST.get('email', '').strip().lower()

        if not email:
            messages.error(request, "O e-mail e obrigatorio.")
            return render(request, self.template_name)

        if User.objects.filter(username=email).exists():
            messages.warning(request, "Este e-mail ja possui uma solicitacao ou cadastro.")
            return redirect('login')

        senha_temporaria = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        User.objects.create_user(
            username=email,
            email=email,
            password=senha_temporaria,
            is_active=False,
        )

        messages.info(
            request,
            "Solicitacao enviada. Assim que a conta for aprovada, voce podera definir sua senha.",
        )
        return redirect('login')


@login_required
def guia_modelos(request):
    return render(request, 'docgen/guia.html')


@login_required
def lista_templates(request):
    templates = Template.objects.filter(ativo=True).select_related('setor', 'area', 'categoria')

    busca = request.GET.get('q')
    setor_id = request.GET.get('setor')
    area_id = request.GET.get('area')
    categoria_id = request.GET.get('categoria')

    if busca:
        templates = templates.filter(Q(titulo__icontains=busca) | Q(descricao__icontains=busca))
    if setor_id and setor_id != 'todos':
        templates = templates.filter(setor_id=setor_id)
    if area_id and area_id != 'todos':
        templates = templates.filter(area_id=area_id)
    if categoria_id and categoria_id != 'todos':
        templates = templates.filter(categoria_id=categoria_id)

    templates = templates.order_by('setor__nome', 'area__nome', 'titulo')
    paginator = Paginator(templates, 9)
    page_obj = paginator.get_page(request.GET.get('page'))

    favoritos_ids = list(
        TemplateFavorito.objects.filter(usuario=request.user).values_list('template_id', flat=True)
    )

    return render(
        request,
        'docgen/lista.html',
        {
            'templates': page_obj,
            'page_obj': page_obj,
            'setores': Setor.objects.all().order_by('nome'),
            'areas': Area.objects.all().order_by('nome'),
            'categorias': Categoria.objects.all().order_by('nome'),
            'filtros_atuais': request.GET,
            'favoritos_ids': favoritos_ids,
        },
    )


@login_required
@staff_member_required
def gerenciar_usuarios(request):
    if request.method == 'POST':
        acao = request.POST.get('acao')
        usuarios_ids = request.POST.getlist('usuarios')

        if not usuarios_ids:
            messages.warning(request, "Nenhum usuario foi selecionado.")
            return redirect('gerenciar_usuarios')

        usuarios = User.objects.filter(id__in=usuarios_ids)

        if acao == 'aprovar':
            usuarios.update(is_active=True)
            messages.success(request, f"{usuarios.count()} usuario(s) aprovado(s) com sucesso.")
        elif acao == 'remover_acesso':
            usuarios = usuarios.exclude(id=request.user.id)
            usuarios.update(is_active=False)
            messages.success(request, f"Acesso revogado para {usuarios.count()} usuario(s).")
        elif acao == 'promover_admin':
            usuarios.update(is_staff=True)
            messages.success(request, f"{usuarios.count()} usuario(s) promovido(s) a administrador.")
        elif acao == 'rebaixar_admin':
            usuarios = usuarios.exclude(id=request.user.id)
            usuarios.update(is_staff=False, is_superuser=False)
            messages.success(request, f"{usuarios.count()} usuario(s) rebaixado(s) para usuario comum.")
        elif acao == 'excluir':
            usuarios = usuarios.exclude(id=request.user.id)
            count = usuarios.count()
            if count > 0:
                try:
                    usuarios.delete()
                    messages.success(request, f"{count} usuario(s) excluido(s) definitivamente.")
                except Exception:
                    messages.error(
                        request,
                        "Um ou mais usuarios possuem historico protegido. Revogue o acesso em vez de excluir.",
                    )

        return redirect('gerenciar_usuarios')

    return render(
        request,
        'docgen/gerenciar_usuarios.html',
        {
            'usuarios_pendentes': User.objects.filter(is_active=False).order_by('-date_joined'),
            'usuarios_ativos': User.objects.filter(is_active=True).order_by('-date_joined'),
        },
    )


@login_required
def gerenciar_equipes(request):
    manageable_ids = _manageable_team_ids(request.user)
    if not (request.user.is_staff or request.user.is_superuser) and not manageable_ids:
        raise PermissionDenied("Voce nao possui equipes sob supervisao.")

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        equipe_pai_id = request.POST.get('equipe_pai')

        if not nome:
            messages.warning(request, "Informe um nome para a estrutura.")
            return redirect('gerenciar_equipes')

        try:
            if equipe_pai_id:
                equipe_pai = get_object_or_404(Equipe, id=equipe_pai_id)
                _require_equipe_manager(request.user, equipe_pai, manageable_ids)
                nova_equipe = Equipe.objects.create(
                    nome=nome,
                    descricao=descricao or None,
                    equipe_pai=equipe_pai,
                )
            else:
                if not (request.user.is_staff or request.user.is_superuser):
                    raise PermissionDenied("Apenas administradores globais podem criar equipes raiz.")
                nova_equipe = Equipe.objects.create(nome=nome, descricao=descricao or None)

            nova_equipe.supervisores.add(request.user)
            messages.success(request, f"Estrutura '{nome}' criada com sucesso.")
        except PermissionDenied as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Erro ao criar a estrutura: {exc}")

        return redirect('gerenciar_equipes')

    equipes = list(
        Equipe.objects.select_related('equipe_pai')
        .prefetch_related('supervisores', 'membros', 'sub_equipes__supervisores', 'sub_equipes__membros')
        .order_by('equipe_pai__nome', 'nome')
    )

    if request.user.is_staff or request.user.is_superuser:
        visible_ids = {equipe.id for equipe in equipes}
        manageable_ids_for_template = visible_ids
    else:
        visible_ids = _visible_team_ids(request.user, manageable_ids)
        equipes = [equipe for equipe in equipes if equipe.id in visible_ids]
        manageable_ids_for_template = manageable_ids

    equipes_pai_disponiveis = [
        equipe
        for equipe in equipes
        if not equipe.equipe_pai_id and equipe.id in manageable_ids_for_template
    ]

    return render(
        request,
        'docgen/gerenciar_equipes.html',
        {
            'equipes': equipes,
            'equipes_pai_disponiveis': equipes_pai_disponiveis,
            'manageable_team_ids': manageable_ids_for_template,
            'can_create_root': request.user.is_staff or request.user.is_superuser,
            'can_delete_teams': request.user.is_staff or request.user.is_superuser,
        },
    )


@login_required
def gerenciar_membros_equipe(request, equipe_id):
    equipe = get_object_or_404(Equipe.objects.prefetch_related('membros', 'supervisores'), id=equipe_id)
    manageable_ids = _manageable_team_ids(request.user)
    _require_equipe_manager(request.user, equipe, manageable_ids)

    if request.method == 'POST':
        acao = request.POST.get('acao')
        usuario_id = request.POST.get('usuario_id')

        if usuario_id:
            usuario = get_object_or_404(User, id=usuario_id)
            if acao == 'adicionar_membro':
                equipe.membros.add(usuario)
                messages.success(request, f"{usuario.username} adicionado como membro.")
            elif acao == 'remover_membro':
                equipe.membros.remove(usuario)
                messages.warning(request, f"{usuario.username} removido dos membros.")
            elif acao == 'adicionar_supervisor':
                equipe.supervisores.add(usuario)
                messages.success(request, f"{usuario.username} promovido a supervisor.")
            elif acao == 'remover_supervisor':
                if usuario == request.user and not (request.user.is_staff or request.user.is_superuser):
                    messages.error(request, "Voce nao pode remover sua propria supervisao.")
                else:
                    equipe.supervisores.remove(usuario)
                    messages.warning(request, f"{usuario.username} removido da supervisao.")

        return redirect('gerenciar_membros_equipe', equipe_id=equipe.id)

    usuarios_na_equipe = list(equipe.membros.values_list('id', flat=True)) + list(
        equipe.supervisores.values_list('id', flat=True)
    )
    usuarios_disponiveis = (
        User.objects.exclude(id__in=usuarios_na_equipe).filter(is_active=True).order_by('first_name', 'username')
    )

    return render(
        request,
        'docgen/gerenciar_membros.html',
        {
            'equipe': equipe,
            'usuarios_disponiveis': usuarios_disponiveis,
        },
    )


@login_required
def toggle_favorito(request, template_id):
    if request.method != 'POST':
        return JsonResponse({'erro': 'Metodo invalido.'}, status=400)

    template = get_object_or_404(Template, id=template_id, ativo=True)
    favorito, created = TemplateFavorito.objects.get_or_create(usuario=request.user, template=template)

    if created:
        return JsonResponse({'status': 'adicionado'})

    favorito.delete()
    return JsonResponse({'status': 'removido'})


@login_required
def minha_biblioteca(request):
    pasta_id = request.GET.get('pasta')
    accessible_folders = _accessible_folders_queryset(request.user).select_related('usuario', 'pasta_pai')
    editable_folders = _editable_folders_queryset(request.user).select_related('usuario', 'pasta_pai')
    accessible_subpastas = Prefetch(
        'subpastas',
        queryset=accessible_folders.order_by('nome'),
    )
    editable_subpastas = Prefetch(
        'subpastas',
        queryset=editable_folders.order_by('nome'),
    )

    pastas = list(
        accessible_folders.filter(pasta_pai__isnull=True)
        .prefetch_related('equipes_permitidas', 'usuarios_permitidos', accessible_subpastas)
        .order_by('nome')
    )
    pastas_editaveis = list(
        editable_folders.filter(pasta_pai__isnull=True)
        .prefetch_related('equipes_permitidas', 'usuarios_permitidos', editable_subpastas)
        .order_by('nome')
    )

    favoritos_query = (
        TemplateFavorito.objects.filter(Q(usuario=request.user) | Q(pasta__in=accessible_folders))
        .select_related('template', 'template__setor', 'pasta', 'usuario')
        .distinct()
    )

    subpastas = []
    if pasta_id == 'sem_pasta':
        favoritos_query = favoritos_query.filter(usuario=request.user, pasta__isnull=True)
    elif pasta_id:
        pasta_atual = get_object_or_404(accessible_folders, id=pasta_id)
        favoritos_query = favoritos_query.filter(pasta=pasta_atual)
        subpastas = list(accessible_folders.filter(pasta_pai=pasta_atual).order_by('nome'))

    favoritos_unicos = _ordered_unique_favorites(list(favoritos_query), request.user)
    paginator = Paginator(favoritos_unicos, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'docgen/minha_biblioteca.html',
        {
            'favoritos': page_obj,
            'page_obj': page_obj,
            'pastas': pastas,
            'pastas_editaveis': pastas_editaveis,
            'subpastas': subpastas,
            'pasta_atual_id': pasta_id,
            'equipes_disponiveis': Equipe.objects.all().order_by('nome'),
            'usuarios_disponiveis': User.objects.filter(is_active=True).order_by('first_name', 'username'),
        },
    )


@login_required
def criar_pasta(request):
    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        pai_id = request.POST.get('pasta_pai')
        nivel_acesso = request.POST.get('nivel_acesso') or PastaPersonalizada.ACESSO_PRIVADO

        if nome:
            pasta_pai = None
            if pai_id:
                pasta_pai = get_object_or_404(_editable_folders_queryset(request.user), id=pai_id)

            pasta = PastaPersonalizada.objects.create(
                usuario=request.user,
                nome=nome,
                escopo=PastaPersonalizada.ESCOPO_BIBLIOTECA,
                pasta_pai=pasta_pai,
            )
            if pasta_pai:
                copy_folder_permissions(pasta_pai, pasta)
            else:
                try:
                    nivel_acesso = normalize_access_level(request.user, nivel_acesso)
                    equipes = Equipe.objects.filter(id__in=request.POST.getlist('equipes'))
                    usuarios = User.objects.filter(id__in=request.POST.getlist('usuarios'), is_active=True)
                    _apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios)
                except PermissionDenied as exc:
                    pasta.delete()
                    messages.error(request, str(exc))
                    return redirect('minha_biblioteca')
            messages.success(request, f"Pasta '{nome}' criada com sucesso.")
        else:
            messages.warning(request, "Informe um nome para a pasta.")

        redirect_url = reverse('minha_biblioteca')
        if pai_id:
            redirect_url += f"?pasta={pai_id}"
        return redirect(redirect_url)

    return redirect('minha_biblioteca')


@login_required
def mover_para_pasta(request, template_id):
    if request.method != 'POST':
        return JsonResponse({'erro': 'Metodo invalido.'}, status=400)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'Payload invalido.'}, status=400)

    favorito = get_object_or_404(TemplateFavorito, template_id=template_id, usuario=request.user)
    nova_pasta_id = payload.get('pasta_id')

    if not nova_pasta_id or nova_pasta_id == 'nenhuma':
        favorito.pasta = None
    else:
        pasta = get_object_or_404(_editable_folders_queryset(request.user), id=nova_pasta_id)
        favorito.pasta = pasta

    favorito.save(update_fields=['pasta'])
    return JsonResponse({'status': 'sucesso'})


@login_required
def excluir_pasta(request, pasta_id):
    pasta = get_object_or_404(_editable_folders_queryset(request.user), id=pasta_id)
    _require_folder_editor(request.user, pasta)

    if request.method == 'POST':
        nome_pasta = pasta.nome
        pasta.delete()
        messages.success(request, f"Pasta '{nome_pasta}' excluida. Os modelos voltaram para 'Sem pasta'.")

    return redirect('minha_biblioteca')


@login_required
def compartilhar_pasta(request):
    if request.method != 'POST':
        return redirect('minha_biblioteca')

    pasta_id = request.POST.get('pasta_id')
    nivel_acesso = request.POST.get('nivel_acesso') or PastaPersonalizada.ACESSO_EQUIPES
    equipes_ids = request.POST.getlist('equipes')
    usuarios_ids = request.POST.getlist('usuarios')

    pasta = get_object_or_404(
        _editable_folders_queryset(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    _require_folder_editor(request.user, pasta)

    nivel_acesso = normalize_access_level(request.user, nivel_acesso)
    equipes = Equipe.objects.filter(id__in=equipes_ids)
    usuarios = User.objects.filter(id__in=usuarios_ids, is_active=True)
    _apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios)
    messages.success(request, f"Permissoes aplicadas a pasta '{pasta.nome}' e suas subpastas.")
    return redirect('minha_biblioteca')


@login_required
def parar_compartilhamento(request, pasta_id):
    pasta = get_object_or_404(
        _editable_folders_queryset(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    _require_folder_editor(request.user, pasta)

    if request.method == 'POST':
        _apply_folder_permissions(pasta, PastaPersonalizada.ACESSO_PRIVADO)
        messages.success(request, f"A pasta '{pasta.nome}' voltou a ser privada.")

    return redirect('minha_biblioteca')


@login_required
def editar_equipe(request, equipe_id):
    equipe = get_object_or_404(Equipe, id=equipe_id)
    manageable_ids = _manageable_team_ids(request.user)
    _require_equipe_manager(request.user, equipe, manageable_ids)

    if request.method == 'POST':
        novo_nome = request.POST.get('nome_equipe', '').strip()
        if novo_nome:
            equipe.nome = novo_nome
            equipe.save(update_fields=['nome'])
            messages.success(request, "Equipe renomeada com sucesso.")
        else:
            messages.warning(request, "O nome da equipe nao pode ficar vazio.")

    return redirect('gerenciar_equipes')


@login_required
@staff_member_required
def excluir_equipe(request, equipe_id):
    equipe = get_object_or_404(Equipe, id=equipe_id)

    if request.method == 'POST':
        nome_antigo = equipe.nome
        equipe.delete()
        messages.success(request, f"Estrutura '{nome_antigo}' removida com sucesso.")

    return redirect('gerenciar_equipes')


@login_required
def criar_nucleo_vinculado(request, equipe_pai_id):
    equipe_pai = get_object_or_404(Equipe.objects.prefetch_related('supervisores', 'membros'), id=equipe_pai_id)
    manageable_ids = _manageable_team_ids(request.user)
    _require_equipe_manager(request.user, equipe_pai, manageable_ids)

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        membros_ids = request.POST.getlist('membros_selecionados')

        if nome:
            novo_nucleo = Equipe.objects.create(
                nome=nome,
                equipe_pai=equipe_pai,
                descricao=f"Nucleo derivado de {equipe_pai.nome}",
            )
            for supervisor in equipe_pai.supervisores.all():
                novo_nucleo.supervisores.add(supervisor)
            if membros_ids:
                novo_nucleo.membros.add(*User.objects.filter(id__in=membros_ids))

            messages.success(request, f"Nucleo '{nome}' criado com sucesso.")
        else:
            messages.warning(request, "Informe um nome para o nucleo.")

    return redirect('gerenciar_equipes')


def definir_senha_primeiro_acesso(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        nova_senha = request.POST.get('password', '')
        confirmacao = request.POST.get('password_confirm', '')

        try:
            user = User.objects.get(username=email)
        except User.DoesNotExist:
            messages.error(request, "Nao encontramos solicitacao para este e-mail. Peca seu acesso primeiro.")
            return redirect('signup')

        if not user.is_active:
            messages.error(request, "Sua conta ainda nao foi aprovada pela supervisao.")
            return redirect('login')

        if user.last_login:
            messages.warning(request, "Esta conta ja foi configurada. Tente fazer login.")
            return redirect('login')

        if nova_senha != confirmacao:
            messages.error(request, "As senhas nao coincidem.")
            return render(request, 'registration/definir_primeira_senha.html')

        try:
            validate_password(nova_senha, user=user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return render(request, 'registration/definir_primeira_senha.html')

        user.set_password(nova_senha)
        user.save(update_fields=['password'])
        messages.success(request, "Senha definida com sucesso. Agora voce pode entrar.")
        return redirect('login')

    return render(request, 'registration/definir_primeira_senha.html')
