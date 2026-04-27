"""Views para o repositorio de arquivos armazenados.

Endpoint principal: arquivos/
- GET: lista os arquivos visiveis ao usuario (proprios + todos se for staff).
- POST: recebe upload (arquivo, tipo opcional, descricao opcional).

Endpoints auxiliares:
- arquivos/<id>/download/: retorna o arquivo binario.
- arquivos/<id>/excluir/: remove (so o dono ou staff).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .models import ArquivoArmazenado


EXTENSOES_PERMITIDAS = {'pdf', 'xlsx', 'csv', 'xls', 'docx', 'doc'}
TAMANHO_MAXIMO_MB = 50


def _user_pode_ver(usuario, arquivo):
    return usuario.is_staff or arquivo.usuario_id == usuario.id


@login_required
@require_http_methods(['GET', 'POST'])
def arquivos_lista(request):
    """Lista + upload na mesma view (o template tem modal de upload)."""

    if request.method == 'POST':
        return _processar_upload(request)

    qs = ArquivoArmazenado.objects.select_related('usuario')
    if not request.user.is_staff:
        qs = qs.filter(usuario=request.user)

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

    obj = ArquivoArmazenado.objects.create(
        arquivo=arquivo,
        nome_original=nome_original,
        tipo=ArquivoArmazenado.detectar_tipo(nome_original),
        descricao=descricao,
        usuario=request.user,
        tamanho_bytes=tamanho,
    )
    messages.success(request, f'Arquivo "{obj.nome_original}" enviado com sucesso.')
    return redirect('arquivos_lista')


@login_required
def arquivo_download(request, arquivo_id):
    obj = get_object_or_404(ArquivoArmazenado, pk=arquivo_id)
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
    obj = get_object_or_404(ArquivoArmazenado, pk=arquivo_id)
    if not _user_pode_ver(request.user, obj):
        raise Http404()
    nome = obj.nome_original
    try:
        obj.arquivo.delete(save=False)
    except Exception:
        pass
    obj.delete()
    messages.success(request, f'Arquivo "{nome}" excluido.')
    return redirect('arquivos_lista')
