"""Views para o repositorio de arquivos armazenados.

Endpoint principal: arquivos/
- GET: lista os arquivos visiveis ao usuario (proprios + todos se for staff).
- POST: recebe upload (arquivo, tipo opcional, descricao opcional).

Endpoints auxiliares:
- arquivos/<id>/download/: retorna o arquivo binario.
- arquivos/<id>/excluir/: remove (so o dono ou staff).
"""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .folder_permissions import (
    accessible_folders_queryset,
    apply_folder_permissions,
    can_access_folder,
    copy_folder_permissions,
    editable_folders_queryset,
    normalize_access_level,
    require_folder_editor,
)
from .models import ArquivoArmazenado, Equipe, PastaPersonalizada


EXTENSOES_PERMITIDAS = {'pdf', 'xlsx', 'csv', 'xls', 'docx', 'doc'}
TAMANHO_MAXIMO_MB = 50


def _user_pode_ver(usuario, arquivo):
    return (
        usuario.is_staff
        or usuario.is_superuser
        or arquivo.usuario_id == usuario.id
        or can_access_folder(usuario, arquivo.pasta)
    )


def _user_pode_gerenciar_arquivo(usuario, arquivo):
    return usuario.is_staff or usuario.is_superuser or arquivo.usuario_id == usuario.id


def _accessible_repo_folders(user):
    return accessible_folders_queryset(user, PastaPersonalizada.ESCOPO_REPOSITORIO)


def _editable_repo_folders(user):
    return editable_folders_queryset(user, PastaPersonalizada.ESCOPO_REPOSITORIO)


def _visible_files_queryset(user):
    qs = ArquivoArmazenado.objects.select_related('usuario', 'pasta')
    if user.is_staff or user.is_superuser:
        return qs
    return qs.filter(Q(usuario=user) | Q(pasta__in=_accessible_repo_folders(user))).distinct()


@login_required
@require_http_methods(['GET', 'POST'])
def arquivos_lista(request):
    """Lista + upload na mesma view (o template tem modal de upload)."""

    if request.method == 'POST':
        return _processar_upload(request)

    pasta_id = request.GET.get('pasta')
    accessible_folders = _accessible_repo_folders(request.user).select_related('usuario', 'pasta_pai')
    editable_folders = _editable_repo_folders(request.user).select_related('usuario', 'pasta_pai')
    accessible_subpastas = Prefetch('subpastas', queryset=accessible_folders.order_by('nome'))
    editable_subpastas = Prefetch('subpastas', queryset=editable_folders.order_by('nome'))

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

    qs = _visible_files_queryset(request.user)
    subpastas = []
    if pasta_id == 'sem_pasta':
        qs = qs.filter(pasta__isnull=True)
        if not (request.user.is_staff or request.user.is_superuser):
            qs = qs.filter(usuario=request.user)
    elif pasta_id:
        pasta_atual = get_object_or_404(accessible_folders, id=pasta_id)
        qs = qs.filter(pasta=pasta_atual)
        subpastas = list(accessible_folders.filter(pasta_pai=pasta_atual).order_by('nome'))

    q = (request.GET.get('q') or '').strip()
    tipo = (request.GET.get('tipo') or '').strip()
    if q:
        qs = qs.filter(Q(nome_original__icontains=q) | Q(descricao__icontains=q))
    if tipo:
        qs = qs.filter(tipo=tipo)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'docgen/arquivos_lista.html', {
        'arquivos': page_obj.object_list,
        'page_obj': page_obj,
        'filtros_atuais': {'q': q, 'tipo': tipo},
        'tipo_choices': ArquivoArmazenado.TIPO_CHOICES,
        'extensoes_permitidas': sorted(EXTENSOES_PERMITIDAS),
        'tamanho_maximo_mb': TAMANHO_MAXIMO_MB,
        'pastas': pastas,
        'pastas_editaveis': pastas_editaveis,
        'subpastas': subpastas,
        'pasta_atual_id': pasta_id,
        'equipes_disponiveis': Equipe.objects.all().order_by('nome'),
        'usuarios_disponiveis': User.objects.filter(is_active=True).order_by('first_name', 'username'),
    })


def _processar_upload(request):
    arquivo = request.FILES.get('arquivo')
    if not arquivo:
        messages.error(request, 'Selecione um arquivo para fazer upload.')
        return redirect('arquivos_lista')

    nome_original = arquivo.name or 'arquivo'
    ext = nome_original.lower().rsplit('.', 1)[-1] if '.' in nome_original else ''
    if ext not in EXTENSOES_PERMITIDAS:
        permitidas = ', '.join(sorted(EXTENSOES_PERMITIDAS))
        messages.error(request, f'Extensao "{ext}" nao permitida. Aceitas: {permitidas}.')
        return redirect('arquivos_lista')

    tamanho = arquivo.size or 0
    limite = TAMANHO_MAXIMO_MB * 1024 * 1024
    if tamanho > limite:
        messages.error(request, f'Arquivo excede {TAMANHO_MAXIMO_MB} MB.')
        return redirect('arquivos_lista')

    descricao = (request.POST.get('descricao') or '').strip()
    pasta_id = request.POST.get('pasta')
    pasta = None
    if pasta_id:
        pasta = get_object_or_404(_editable_repo_folders(request.user), id=pasta_id)

    obj = ArquivoArmazenado.objects.create(
        arquivo=arquivo,
        nome_original=nome_original,
        tipo=ArquivoArmazenado.detectar_tipo(nome_original),
        descricao=descricao,
        pasta=pasta,
        usuario=request.user,
        tamanho_bytes=tamanho,
    )
    messages.success(request, f'Arquivo "{obj.nome_original}" enviado com sucesso.')
    return redirect('arquivos_lista')


@login_required
def arquivo_download(request, arquivo_id):
    obj = get_object_or_404(ArquivoArmazenado.objects.select_related('pasta', 'usuario'), pk=arquivo_id)
    if not _user_pode_ver(request.user, obj):
        raise Http404()
    try:
        f = obj.arquivo.open('rb')
    except FileNotFoundError:
        raise Http404('Arquivo nao encontrado no storage.')
    response = FileResponse(f, as_attachment=True, filename=obj.nome_original)
    return response


@login_required
@require_POST
def arquivo_excluir(request, arquivo_id):
    obj = get_object_or_404(ArquivoArmazenado.objects.select_related('pasta', 'usuario'), pk=arquivo_id)
    if not _user_pode_gerenciar_arquivo(request.user, obj):
        raise Http404()
    nome = obj.nome_original
    try:
        obj.arquivo.delete(save=False)
    except Exception:
        pass
    obj.delete()
    messages.success(request, f'Arquivo "{nome}" excluido.')
    return redirect('arquivos_lista')


@login_required
@require_POST
def criar_pasta_arquivo(request):
    nome = (request.POST.get('nome') or '').strip()
    pai_id = request.POST.get('pasta_pai')
    nivel_acesso = request.POST.get('nivel_acesso') or PastaPersonalizada.ACESSO_PRIVADO

    if not nome:
        messages.warning(request, 'Informe um nome para a pasta.')
        return redirect('arquivos_lista')

    pasta_pai = None
    if pai_id:
        pasta_pai = get_object_or_404(_editable_repo_folders(request.user), id=pai_id)

    pasta = PastaPersonalizada.objects.create(
        usuario=request.user,
        nome=nome,
        escopo=PastaPersonalizada.ESCOPO_REPOSITORIO,
        pasta_pai=pasta_pai,
    )
    if pasta_pai:
        copy_folder_permissions(pasta_pai, pasta)
    else:
        try:
            nivel_acesso = normalize_access_level(request.user, nivel_acesso)
            equipes = Equipe.objects.filter(id__in=request.POST.getlist('equipes'))
            usuarios = User.objects.filter(id__in=request.POST.getlist('usuarios'), is_active=True)
            apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios)
        except PermissionDenied as exc:
            pasta.delete()
            messages.error(request, str(exc))
            return redirect('arquivos_lista')

    messages.success(request, f'Pasta "{nome}" criada.')
    if pai_id:
        return redirect(f"{reverse('arquivos_lista')}?pasta={pai_id}")
    return redirect('arquivos_lista')


@login_required
@require_POST
def arquivo_mover(request, arquivo_id):
    obj = get_object_or_404(ArquivoArmazenado.objects.select_related('pasta', 'usuario'), pk=arquivo_id)
    if not _user_pode_gerenciar_arquivo(request.user, obj):
        return JsonResponse({'erro': 'Sem permissao para mover este arquivo.'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'Payload invalido.'}, status=400)

    pasta_id = payload.get('pasta_id')
    if not pasta_id or pasta_id == 'nenhuma':
        obj.pasta = None
    else:
        obj.pasta = get_object_or_404(_editable_repo_folders(request.user), id=pasta_id)
    obj.save(update_fields=['pasta', 'atualizado_em'])
    return JsonResponse({'status': 'sucesso'})


@login_required
@require_POST
def excluir_pasta_arquivo(request, pasta_id):
    pasta = get_object_or_404(
        _editable_repo_folders(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    require_folder_editor(request.user, pasta)
    nome = pasta.nome
    pasta.delete()
    messages.success(request, f'Pasta "{nome}" excluida. Os arquivos voltaram para "Sem pasta".')
    return redirect('arquivos_lista')


@login_required
@require_POST
def compartilhar_pasta_arquivo(request):
    pasta_id = request.POST.get('pasta_id')
    nivel_acesso = request.POST.get('nivel_acesso') or PastaPersonalizada.ACESSO_EQUIPES
    pasta = get_object_or_404(
        _editable_repo_folders(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    require_folder_editor(request.user, pasta)

    nivel_acesso = normalize_access_level(request.user, nivel_acesso)
    equipes = Equipe.objects.filter(id__in=request.POST.getlist('equipes'))
    usuarios = User.objects.filter(id__in=request.POST.getlist('usuarios'), is_active=True)
    apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios)
    messages.success(request, f'Permissoes aplicadas a pasta "{pasta.nome}" e suas subpastas.')
    return redirect('arquivos_lista')


@login_required
@require_POST
def parar_compartilhamento_pasta_arquivo(request, pasta_id):
    pasta = get_object_or_404(
        _editable_repo_folders(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    require_folder_editor(request.user, pasta)
    apply_folder_permissions(pasta, PastaPersonalizada.ACESSO_PRIVADO)
    messages.success(request, f'A pasta "{pasta.nome}" voltou a ser privada.')
    return redirect('arquivos_lista')
