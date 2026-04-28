from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import ArquivoProcesso, ExecucaoCapturaProcesso, LoteImportacaoProcessos, Processo, ProcessoStatus
from .processos_constants import (
    COLUNAS_OBRIGATORIAS_PROCESSOS,
    COLUNAS_OPCIONAIS_PROCESSOS,
    TRIBUNAIS_ESTADUAIS,
)
from .processos_forms import ImportarLoteProcessosForm
from .processos_services import importar_lote_processos, reprocessar_processo


STATUS_BADGES = {
    ProcessoStatus.PENDENTE: 'secondary',
    ProcessoStatus.EM_FILA: 'info',
    ProcessoStatus.PROCESSANDO: 'primary',
    ProcessoStatus.BAIXADO: 'success',
    ProcessoStatus.PROCESSO_NAO_ENCONTRADO: 'warning',
    ProcessoStatus.PETICAO_NAO_LOCALIZADA: 'warning',
    ProcessoStatus.FALHA_TECNICA: 'danger',
}


def _require_staff_user(user):
    if user.is_staff or user.is_superuser:
        return
    raise PermissionDenied("Apenas perfis administrativos podem acessar esta area.")


def _processos_queryset_for_user(user):
    queryset = Processo.objects.select_related('usuario').prefetch_related('execucoes', 'arquivos')
    if user.is_staff or user.is_superuser:
        return queryset
    return queryset.filter(usuario=user)


def _require_processo_access(user, processo):
    if user.is_staff or user.is_superuser or processo.usuario_id == user.id:
        return
    raise PermissionDenied("Voce nao pode acessar este processo.")


@login_required
def processos_lista(request):
    processos = _processos_queryset_for_user(request.user)

    status = request.GET.get('status')
    tribunal = request.GET.get('tribunal')
    busca = request.GET.get('q', '').strip()
    usuario_email = request.GET.get('usuario_email', '').strip()

    if status:
        processos = processos.filter(status_atual=status)
    if tribunal:
        processos = processos.filter(tribunal_codigo=tribunal)
    if busca:
        processos = processos.filter(numero_cnj__icontains=busca)
    if usuario_email and (request.user.is_staff or request.user.is_superuser):
        processos = processos.filter(usuario__username__icontains=usuario_email)

    paginator = Paginator(processos.order_by('-atualizado_em'), 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'docgen/processos_lista.html',
        {
            'processos': page_obj,
            'page_obj': page_obj,
            'status_choices': ProcessoStatus.choices,
            'tribunais': sorted(TRIBUNAIS_ESTADUAIS.items()),
            'status_badges': STATUS_BADGES,
            'filtros_atuais': request.GET,
            'can_filter_usuario': request.user.is_staff or request.user.is_superuser,
        },
    )


@login_required
def processo_detalhe(request, processo_id):
    processo = get_object_or_404(_processos_queryset_for_user(request.user), id=processo_id)
    _require_processo_access(request.user, processo)

    execucoes = processo.execucoes.select_related('lote').order_by('-criado_em')
    arquivo_atual = processo.arquivo_peticao_atual

    return render(
        request,
        'docgen/processo_detalhe.html',
        {
            'processo': processo,
            'execucoes': execucoes,
            'arquivo_atual': arquivo_atual,
            'status_badges': STATUS_BADGES,
        },
    )


@login_required
def download_arquivo_processo(request, arquivo_id):
    arquivo = get_object_or_404(
        ArquivoProcesso.objects.select_related('processo', 'processo__usuario'),
        id=arquivo_id,
    )
    _require_processo_access(request.user, arquivo.processo)
    return FileResponse(
        arquivo.arquivo.open('rb'),
        as_attachment=True,
        filename=arquivo.arquivo.name.split('/')[-1],
    )


@login_required
def processos_importar_lote(request):
    _require_staff_user(request.user)

    if request.method == 'POST':
        form = ImportarLoteProcessosForm(request.POST, request.FILES)
        if form.is_valid():
            lote = importar_lote_processos(
                usuario_admin=request.user,
                planilha=form.cleaned_data['planilha'],
                dados_planilha=form.cleaned_data['dados_planilha'],
            )
            messages.success(
                request,
                (
                    f"Lote #{lote.pk} importado com sucesso. "
                    f"{lote.total_processos_criados} processo(s) criado(s) e "
                    f"{lote.total_processos_atualizados} atualizado(s)."
                ),
            )
            return redirect('processos_monitoramento')
    else:
        form = ImportarLoteProcessosForm()

    return render(
        request,
        'docgen/processos_importar_lote.html',
        {
            'form': form,
            'colunas_obrigatorias': COLUNAS_OBRIGATORIAS_PROCESSOS,
            'colunas_opcionais': COLUNAS_OPCIONAIS_PROCESSOS,
        },
    )


@login_required
def processos_monitoramento(request):
    _require_staff_user(request.user)

    execucoes = ExecucaoCapturaProcesso.objects.select_related(
        'processo',
        'processo__usuario',
        'lote',
    ).order_by('-criado_em')
    lotes_queryset = LoteImportacaoProcessos.objects.select_related('usuario').order_by('-criado_em')
    if not (request.user.is_superuser or request.user.is_staff):
        lotes_queryset = lotes_queryset.filter(usuario=request.user)
    lotes = list(lotes_queryset[:5])

    status = request.GET.get('status')
    tribunal = request.GET.get('tribunal')
    busca = request.GET.get('q', '').strip()
    lote_id = (request.GET.get('lote') or '').strip().lstrip('#')

    if status:
        execucoes = execucoes.filter(status=status)
    if tribunal:
        execucoes = execucoes.filter(processo__tribunal_codigo=tribunal)
    if busca:
        execucoes = execucoes.filter(processo__numero_cnj__icontains=busca)
    if lote_id:
        execucoes = execucoes.filter(lote_id=lote_id)

    paginator = Paginator(execucoes, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'docgen/processos_monitoramento.html',
        {
            'execucoes': page_obj,
            'page_obj': page_obj,
            'status_choices': ProcessoStatus.choices,
            'tribunais': sorted(TRIBUNAIS_ESTADUAIS.items()),
            'status_badges': STATUS_BADGES,
            'filtros_atuais': request.GET,
            'lotes_recentes': lotes,
        },
    )


@login_required
def reprocessar_processo_view(request, processo_id):
    _require_staff_user(request.user)
    processo = get_object_or_404(Processo.objects.select_related('usuario'), id=processo_id)

    if request.method == 'POST':
        reprocessar_processo(processo, usuario=request.user)
        messages.success(request, f"O processo {processo.numero_cnj} foi reenfileirado para captura.")

    return redirect('processo_detalhe', processo_id=processo.id)
