import json
import logging
import secrets
import string
from datetime import datetime

logger = logging.getLogger(__name__)

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    IntegerField,
    Min,
    Prefetch,
    ProtectedError,
    Q,
    Value,
    When,
)
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
from .template_validacao import analisar_template_docx
from .utils import (
    carregar_campos_template,
    enviar_lote_obrigacao_fazer,
    extrair_tags_do_docx,
    renderizar_template_docx,
)


def _render_relatorio_validacao(request, relatorio, url_voltar, template_existente=None):
    """Tela de pré-validação reprovada: mostra cada problema já localizado.

    Usada pelos três caminhos que aceitam .docx (upload manual, sugestão por
    IA e troca de arquivo na edição) para que a mensagem seja sempre a mesma.
    """
    return render(
        request,
        'docgen/relatorio_validacao.html',
        {
            'relatorio': relatorio,
            'url_voltar': url_voltar,
            'template_existente': template_existente,
        },
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


def _unique_favorites_queryset(base_queryset, user):
    """Para cada template_id, retorna um único TemplateFavorito — preferindo o do
    próprio `user` quando existir; caso contrário, o favorito alheio de menor id.

    Implementação portátil (Postgres + SQLite): combina IDs do user logado com
    IDs alheios deduplicados via Min(id) por template. Retorna um QuerySet pronto
    para paginação, ordenado alfabeticamente por título.
    """
    meus_ids = list(
        base_queryset.filter(usuario=user).values_list('id', flat=True)
    )
    meus_template_ids = list(
        base_queryset.filter(usuario=user).values_list('template_id', flat=True)
    )
    alheios_ids = list(
        base_queryset
        .exclude(template_id__in=meus_template_ids)
        .values('template_id')
        .annotate(escolhido=Min('id'))
        .values_list('escolhido', flat=True)
    )

    return (
        TemplateFavorito.objects
        .filter(id__in=meus_ids + alheios_ids)
        .select_related('template', 'template__setor', 'pasta', 'usuario')
        .order_by('template__titulo')
    )


def _nome_arquivo_gerado(titulo_template):
    nome_base = titulo_template.strip().replace(' ', '_') or "documento"
    return f"{nome_base}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"


@login_required
@staff_member_required
def sugerir_template_ia(request):
    """Upload de DOCX exemplo → Claude sugere placeholders → cria Template.

    Redireciona para `configurar_template` com os campos já pré-populados, onde
    o usuário revisa antes de salvar.
    """
    from django.core.files.base import ContentFile
    from . import template_ai

    if not settings.ANTHROPIC_API_KEY:
        messages.error(
            request,
            "Sugestão por IA indisponível: ANTHROPIC_API_KEY não configurada no servidor.",
        )
        return redirect('criar_template')

    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        descricao = request.POST.get('descricao', '').strip()
        setor_id = request.POST.get('setor')
        area_id = request.POST.get('area')
        categoria_id = request.POST.get('categoria')
        arquivo = request.FILES.get('arquivo')

        if not arquivo or not titulo or not setor_id:
            messages.error(request, "Preencha os campos obrigatórios e envie um arquivo .docx exemplo.")
            return redirect('sugerir_template_ia')

        if not arquivo.name.lower().endswith('.docx'):
            messages.error(request, "Apenas arquivos .docx são aceitos pela sugestão por IA.")
            return redirect('sugerir_template_ia')

        try:
            docx_bytes = arquivo.read()
            resultado = template_ai.gerar_sugestao_de_template(docx_bytes)
        except template_ai.IAIndisponivelError as exc:
            messages.error(request, str(exc))
            return redirect('criar_template')
        except Exception as exc:
            messages.error(
                request,
                f"Não foi possível analisar o arquivo: {exc}. Tente o upload manual.",
            )
            return redirect('criar_template')

        if not resultado.placeholders:
            messages.warning(
                request,
                "A IA não identificou trechos variáveis. Talvez a peça seja muito curta ou "
                "já esteja em formato de template. Tente upload manual.",
            )
            return redirect('criar_template')

        configuracao_campos = [
            {
                'tag': p.get('tag', ''),
                'label': p.get('label', '') or p.get('tag', '').replace('_', ' ').title(),
                'tipo': p.get('tipo', 'text'),
                'dependencia': '',
                'opcoes': p.get('opcoes', ''),
            }
            for p in resultado.placeholders
            if p.get('tag')
        ]

        # Normaliza tags Jinja com acentos/cedilha → ASCII (defesa em
        # profundidade — Claude geralmente gera ASCII, mas se um dia gerar
        # com acento o template ainda funcionará).
        from . import template_utils
        docx_normalizado, renames = template_utils.normalize_jinja_tags_in_docx(
            resultado.docx_modificado
        )
        configuracao_campos = template_utils.apply_renames_to_configuracao(
            configuracao_campos, renames
        )

        # Pré-validação: nenhum modelo com tag quebrada entra no catálogo.
        relatorio = analisar_template_docx(docx_normalizado)
        if not relatorio.ok:
            messages.error(
                request,
                "A IA gerou um modelo que não passou na pré-validação. "
                "Tente o upload manual com a peça-exemplo, ou refaça a sugestão.",
            )
            return _render_relatorio_validacao(
                request, relatorio, reverse('sugerir_template_ia')
            )

        try:
            template = Template.objects.create(
                titulo=titulo,
                descricao=descricao,
                setor_id=setor_id,
                area_id=area_id or None,
                categoria_id=categoria_id or None,
                arquivo_template=ContentFile(docx_normalizado, name=arquivo.name),
                configuracao_campos=configuracao_campos,
                ativo=True,
                criado_por=request.user,
            )
        except Exception as exc:
            messages.error(request, f"Erro ao salvar o modelo: {exc}")
            return redirect('sugerir_template_ia')

        messages.success(
            request,
            f"IA sugeriu {len(configuracao_campos)} campo(s). Revise abaixo antes de finalizar. "
            f"(Tokens: {resultado.tokens_input} in / {resultado.tokens_output} out, "
            f"{resultado.tokens_cached} cached)",
        )
        return redirect('configurar_template', template_id=template.id)

    return render(
        request,
        'docgen/sugerir_template.html',
        {
            'setores': Setor.objects.all().order_by('nome'),
            'areas': Area.objects.all().order_by('nome'),
            'categorias': Categoria.objects.all().order_by('nome'),
        },
    )


@login_required
@staff_member_required
def criar_template(request):
    from django.core.files.base import ContentFile
    from . import template_utils

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
                # Normaliza tags Jinja com acentos/cedilha → versão ASCII,
                # evitando o erro "expected token 'end of print statement'"
                # causado pela fragmentação de runs do Word.
                docx_bytes_normalizado, renames = template_utils.normalize_jinja_tags_in_docx(
                    arquivo.read()
                )

                # Pré-validação: se houver qualquer tag quebrada, NÃO cria o
                # Template — devolve o relatório apontando onde está cada erro.
                relatorio = analisar_template_docx(docx_bytes_normalizado)
                if not relatorio.ok:
                    return _render_relatorio_validacao(
                        request, relatorio, reverse('criar_template')
                    )

                arquivo_final = ContentFile(docx_bytes_normalizado, name=arquivo.name)

                template = Template.objects.create(
                    titulo=titulo,
                    descricao=descricao,
                    setor_id=setor_id,
                    area_id=area_id or None,
                    categoria_id=categoria_id or None,
                    arquivo_template=arquivo_final,
                    ativo=True,
                    criado_por=request.user,
                )
                if renames:
                    messages.info(
                        request,
                        f"{len(renames)} variável(eis) com acento/cedilha foram renomeadas "
                        f"para evitar erro de renderização: "
                        + ', '.join(f"{a} → {n}" for a, n in renames.items()),
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
def configurar_template(request, template_id):
    template = get_object_or_404(Template, pk=template_id)
    _require_gerente_template(request.user, template)
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


def _sincronizar_configuracao_campos(template):
    """Reconcilia configuracao_campos com as tags do .docx atual.

    Usado depois de trocar o arquivo de um modelo já existente: preserva o
    label/tipo/dependência das tags que continuam no documento e acrescenta
    as novas com valores padrão. Tags que sumiram do .docx são descartadas.
    """
    tags = extrair_tags_do_docx(template.arquivo_template.path)
    atual = {
        item.get('tag'): item
        for item in (template.configuracao_campos or [])
        if item.get('tag')
    }
    return [
        atual.get(
            tag,
            {
                'tag': tag,
                'label': tag.replace('_', ' ').title(),
                'tipo': 'text',
                'dependencia': '',
                'opcoes': '',
            },
        )
        for tag in tags
    ]


def _pode_gerenciar_template(user, template):
    """Staff/superuser gerenciam qualquer modelo; o autor gerencia o dele.

    Vale para editar, substituir o .docx, remapear os campos e excluir.
    """
    if user.is_staff or user.is_superuser:
        return True
    return template.criado_por_id is not None and template.criado_por_id == user.id


def _require_gerente_template(user, template):
    if not _pode_gerenciar_template(user, template):
        raise PermissionDenied(
            "Você só pode alterar modelos que você mesmo criou."
        )


@login_required
def editar_template(request, template_id):
    """Edita metadados do modelo (título, descrição, classificação) e,
    opcionalmente, substitui o arquivo .docx base — tudo pela própria
    aplicação, sem passar pelo admin do Django."""
    from . import template_utils

    template = get_object_or_404(Template, pk=template_id)
    _require_gerente_template(request.user, template)

    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        setor_id = request.POST.get('setor')

        if not titulo or not setor_id:
            messages.error(request, "Título e setor são obrigatórios.")
            return redirect('editar_template', template_id=template.id)

        arquivo = request.FILES.get('arquivo')
        trocou_arquivo = False

        if arquivo:
            try:
                docx_bytes, renames = template_utils.normalize_jinja_tags_in_docx(
                    arquivo.read()
                )
            except Exception as exc:
                messages.error(request, f"Não foi possível ler o .docx enviado: {exc}")
                return redirect('editar_template', template_id=template.id)

            # Mesma pré-validação do upload: um arquivo quebrado nunca
            # substitui um modelo que está funcionando.
            relatorio = analisar_template_docx(docx_bytes)
            if not relatorio.ok:
                return _render_relatorio_validacao(
                    request,
                    relatorio,
                    reverse('editar_template', args=[template.id]),
                    template_existente=template,
                )

            template.arquivo_template.save(arquivo.name, ContentFile(docx_bytes), save=False)
            template.configuracao_campos = template_utils.apply_renames_to_configuracao(
                template.configuracao_campos, renames
            )
            trocou_arquivo = True

        template.titulo = titulo
        template.descricao = request.POST.get('descricao', '').strip()
        template.setor_id = setor_id
        template.area_id = request.POST.get('area') or None
        template.categoria_id = request.POST.get('categoria') or None

        try:
            template.save()
        except Exception as exc:
            messages.error(request, f"Erro ao salvar o modelo: {exc}")
            return redirect('editar_template', template_id=template.id)

        if trocou_arquivo:
            template.configuracao_campos = _sincronizar_configuracao_campos(template)
            template.save(update_fields=['configuracao_campos'])
            messages.success(
                request,
                f"Modelo '{template.titulo}' atualizado e arquivo substituído. "
                "Confira o mapeamento dos campos abaixo.",
            )
            return redirect('configurar_template', template_id=template.id)

        messages.success(request, f"Modelo '{template.titulo}' atualizado com sucesso.")
        return redirect('lista_templates')

    return render(
        request,
        'docgen/editar_template.html',
        {
            'template': template,
            'setores': Setor.objects.all().order_by('nome'),
            'areas': Area.objects.all().order_by('nome'),
            'categorias': Categoria.objects.all().order_by('nome'),
            'qtd_documentos': DocumentoGerado.objects.filter(template=template).count(),
        },
    )


@login_required
def excluir_template(request, template_id):
    """Exclui o modelo. Permitido ao staff e a quem criou o modelo.

    Se já houver documentos gerados a partir dele, o DocumentoGerado.template
    é PROTECT — apagar levaria o histórico junto, então nesse caso arquivamos
    (ativo=False) em vez de excluir."""
    template = get_object_or_404(Template, pk=template_id)
    _require_gerente_template(request.user, template)

    if request.method != 'POST':
        return redirect('lista_templates')

    titulo = template.titulo
    qtd_documentos = DocumentoGerado.objects.filter(template=template).count()

    if qtd_documentos:
        template.ativo = False
        template.save(update_fields=['ativo'])
        messages.warning(
            request,
            f"'{titulo}' foi arquivado em vez de excluído: há {qtd_documentos} "
            "documento(s) já gerado(s) a partir dele e o histórico seria perdido. "
            "Ele sai do catálogo e pode ser restaurado em Catálogo → Arquivados.",
        )
        return redirect('lista_templates')

    try:
        template.delete()
    except ProtectedError:
        # Defesa contra corrida: alguém gerou um documento entre a contagem
        # acima e o delete.
        template.ativo = False
        template.save(update_fields=['ativo'])
        messages.warning(
            request,
            f"'{titulo}' foi arquivado — surgiram registros vinculados que "
            "impedem a exclusão definitiva.",
        )
        return redirect('lista_templates')

    messages.success(request, f"Modelo '{titulo}' excluído definitivamente.")
    return redirect('lista_templates')


@login_required
def restaurar_template(request, template_id):
    template = get_object_or_404(Template, pk=template_id)
    _require_gerente_template(request.user, template)

    if request.method == 'POST':
        template.ativo = True
        template.save(update_fields=['ativo'])
        messages.success(request, f"Modelo '{template.titulo}' voltou para o catálogo.")

    return redirect('lista_templates')


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
            # Log do traceback completo pro stdout do gunicorn (visível no
            # painel de logs do Coolify). Sem isso o erro fica invisível —
            # só o usuário vê a mensagem na tela.
            logger.exception(
                "gerar_documento: falha ao renderizar template_id=%s titulo=%r path=%s",
                template.id,
                template.titulo,
                template.arquivo_template.name,
            )
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
    # Aba de arquivados: modelos com ativo=False, que saíram do catálogo mas
    # continuam no banco por causa do histórico. Staff vê todos; o usuário
    # comum vê só os que ele mesmo criou (senão arquivaria sem poder desfazer).
    eh_staff = request.user.is_staff or request.user.is_superuser
    mostrar_arquivados = request.GET.get('arquivados') == '1'

    templates = Template.objects.filter(ativo=not mostrar_arquivados).select_related(
        'setor', 'area', 'categoria', 'criado_por'
    )
    if mostrar_arquivados and not eh_staff:
        templates = templates.filter(criado_por=request.user)

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
            'mostrar_arquivados': mostrar_arquivados,
            'total_arquivados': (
                Template.objects.filter(ativo=False).count()
                if eh_staff
                else Template.objects.filter(ativo=False, criado_por=request.user).count()
            ),
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
def adicionar_favorito(request, template_id):
    """Cria um favorito do usuário logado para o template. Idempotente:
    se já existir, devolve `ja_existe` sem alterar nada (não toca pasta).
    """
    if request.method != 'POST':
        return JsonResponse({'erro': 'Metodo invalido.'}, status=400)

    template = get_object_or_404(Template, id=template_id, ativo=True)
    _, created = TemplateFavorito.objects.get_or_create(usuario=request.user, template=template)
    return JsonResponse({'status': 'adicionado' if created else 'ja_existe'})


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

    pastas_raiz = list(
        accessible_folders.filter(pasta_pai__isnull=True)
        .prefetch_related('equipes_permitidas', 'usuarios_permitidos', accessible_subpastas)
        .order_by('nome')
    )
    minhas_pastas = [p for p in pastas_raiz if p.usuario_id == request.user.id]
    pastas_compartilhadas_comigo = [p for p in pastas_raiz if p.usuario_id != request.user.id]
    pastas_editaveis = list(
        editable_folders.filter(pasta_pai__isnull=True)
        .prefetch_related('equipes_permitidas', 'usuarios_permitidos', editable_subpastas)
        .order_by('nome')
    )

    favoritos_base = TemplateFavorito.objects.filter(
        Q(usuario=request.user) | Q(pasta__in=accessible_folders)
    )

    subpastas = []
    if pasta_id == 'sem_pasta':
        favoritos_base = favoritos_base.filter(usuario=request.user, pasta__isnull=True)
    elif pasta_id:
        pasta_atual = get_object_or_404(accessible_folders, id=pasta_id)
        favoritos_base = favoritos_base.filter(pasta=pasta_atual)
        subpastas = list(accessible_folders.filter(pasta_pai=pasta_atual).order_by('nome'))

    favoritos_unicos = _unique_favorites_queryset(favoritos_base, request.user)
    paginator = Paginator(favoritos_unicos, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'docgen/minha_biblioteca.html',
        {
            'favoritos': page_obj,
            'page_obj': page_obj,
            'minhas_pastas': minhas_pastas,
            'pastas_compartilhadas_comigo': pastas_compartilhadas_comigo,
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

    try:
        favorito = TemplateFavorito.objects.get(template_id=template_id, usuario=request.user)
    except TemplateFavorito.DoesNotExist:
        return JsonResponse(
            {'erro': 'Voce ainda nao adicionou este modelo a sua biblioteca.'},
            status=403,
        )
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
    cascade = request.POST.get('aplicar_subpastas') == 'on'

    pasta = get_object_or_404(
        _editable_folders_queryset(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    _require_folder_editor(request.user, pasta)

    nivel_acesso = normalize_access_level(request.user, nivel_acesso)
    equipes = Equipe.objects.filter(id__in=equipes_ids)
    usuarios = User.objects.filter(id__in=usuarios_ids, is_active=True)
    apply_folder_permissions(pasta, nivel_acesso, equipes, usuarios, cascade=cascade)
    if cascade:
        messages.success(request, f"Permissoes aplicadas a pasta '{pasta.nome}' e a todas as suas subpastas.")
    else:
        messages.success(request, f"Permissoes aplicadas a pasta '{pasta.nome}'. Subpastas mantiveram suas permissoes.")
    return redirect('minha_biblioteca')


@login_required
def parar_compartilhamento(request, pasta_id):
    pasta = get_object_or_404(
        _editable_folders_queryset(request.user).prefetch_related('subpastas'),
        id=pasta_id,
    )
    _require_folder_editor(request.user, pasta)

    if request.method == 'POST':
        apply_folder_permissions(pasta, PastaPersonalizada.ACESSO_PRIVADO)
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
