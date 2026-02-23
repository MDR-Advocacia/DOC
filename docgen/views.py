# docgen/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse_lazy
from django.views import generic
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.db.models import ProtectedError
from .models import Equipe
from django.db import models

# Bibliotecas de processamento de DOCX
from docxtpl import DocxTemplate, InlineImage 
from docx.shared import Mm 
import io
from datetime import datetime

# Seus Models e Utils
from .models import Template, DocumentoGerado, Setor, Categoria, Area, PastaPersonalizada, TemplateFavorito
from .utils import extrair_tags_do_docx 

import json

# ==============================================================================
#  ÁREA ADMINISTRATIVA (SUPERVISORES)
# ==============================================================================

@login_required
@staff_member_required
def criar_template(request):
    """
    PASSO 1: Upload do arquivo DOCX e dados básicos.
    Ao salvar, redireciona automaticamente para a configuração dos campos.
    """
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descricao = request.POST.get('descricao')
        setor_id = request.POST.get('setor')
        area_id = request.POST.get('area')
        categoria_id = request.POST.get('categoria')
        arquivo = request.FILES.get('arquivo')
        
        if not arquivo or not titulo or not setor_id:
            messages.error(request, "Preencha os campos obrigatórios e envie um arquivo.")
        else:
            try:
                # Cria o objeto no banco
                novo_template = Template.objects.create(
                    titulo=titulo,
                    descricao=descricao,
                    setor_id=setor_id,
                    area_id=area_id if area_id else None,
                    categoria_id=categoria_id if categoria_id else None,
                    arquivo_template=arquivo,
                    ativo=True
                )
                
                messages.success(request, "Arquivo enviado! Agora configure os campos identificados.")
                # REDIRECIONAMENTO MÁGICO: Vai direto para a tela de configurar tags
                return redirect('configurar_template', template_id=novo_template.id)
                
            except Exception as e:
                messages.error(request, f"Erro ao salvar: {e}")

    # Dropdowns para o formulário
    setores = Setor.objects.all().order_by('nome')
    areas = Area.objects.all().order_by('nome')
    categorias = Categoria.objects.all().order_by('nome')
    
    return render(request, 'docgen/novo_template.html', {
        'setores': setores,
        'areas': areas,
        'categorias': categorias
    })

@login_required
@staff_member_required
def configurar_template(request, template_id):
    """
    PASSO 2: Tela para definir Labels, Tipos e DEPENDÊNCIAS das variáveis.
    """
    template = get_object_or_404(Template, pk=template_id)
    
    # 1. O Robô lê o arquivo físico e acha as tags
    # Nota: Com o novo utils.py, isso já traz na ordem correta e inclui os 'if'
    tags_encontradas = extrair_tags_do_docx(template.arquivo_template.path)
    
    # 2. Carrega configuração existente
    config_atual = template.configuracao_campos or []
    dict_config = {item['tag']: item for item in config_atual}

    # 3. Salvar Configuração (POST)
    if request.method == 'POST':
        nova_configuracao = []
        for tag in tags_encontradas:
            label_input = request.POST.get(f'label_{tag}')
            tipo_input = request.POST.get(f'tipo_{tag}')
            dependencia_input = request.POST.get(f'dependencia_{tag}') # <--- NOVO (Captura quem é o pai)
            
            nova_configuracao.append({
                "tag": tag,
                "label": label_input or tag.replace('_', ' ').title(),
                "tipo": tipo_input,
                "dependencia": dependencia_input # <--- NOVO (Salva no banco)
            })
        
        template.configuracao_campos = nova_configuracao
        template.save()
        messages.success(request, f"Configuração salva com sucesso!")
        return redirect('lista_templates')

    # 4. Exibir (GET)
    campos_para_exibir = []
    for tag in tags_encontradas:
        dados = dict_config.get(tag, {})
        campos_para_exibir.append({
            'tag': tag,
            'label': dados.get('label', tag.replace('_', ' ').title()),
            'tipo': dados.get('tipo', 'text'),
            'dependencia': dados.get('dependencia', '') # <--- NOVO (Lê do banco para a tela)
        })

    return render(request, 'docgen/configurar_template.html', {
        'template': template,
        'campos': campos_para_exibir,
        'todas_tags': tags_encontradas # <--- NOVO (Necessário para popular o dropdown de pais)
    })


# ==============================================================================
#  ÁREA OPERACIONAL (ADVOGADOS)
# ==============================================================================

@login_required
def home_dashboard(request):
    """Landing Page com Gráficos e Totais"""
    total_docs = DocumentoGerado.objects.count()
    total_templates = Template.objects.filter(ativo=True).count()
    
    # Gráfico 1: Docs por Setor
    docs_por_setor = DocumentoGerado.objects.values('template__setor__nome')\
        .annotate(qtd=Count('id')).order_by('-qtd')
    
    labels_setor = [item['template__setor__nome'] for item in docs_por_setor]
    data_setor = [item['qtd'] for item in docs_por_setor]

    # Gráfico 2: Docs por Mês
    docs_por_mes = DocumentoGerado.objects.annotate(mes=TruncMonth('data_geracao'))\
        .values('mes').annotate(qtd=Count('id')).order_by('mes')
    
    labels_mes = [item['mes'].strftime('%B/%Y') for item in docs_por_mes]
    data_mes = [item['qtd'] for item in docs_por_mes]

    return render(request, 'docgen/home.html', {
        'total_docs': total_docs,
        'total_templates': total_templates,
        'labels_setor': labels_setor,
        'data_setor': data_setor,
        'labels_mes': labels_mes,
        'data_mes': data_mes,
    })

@login_required
def gerar_documento(request, template_id):
    """
    Motor de Geração: Recebe o POST do formulário dinâmico,
    processa no DocxTemplate e devolve o arquivo para download.
    """
    template_db = get_object_or_404(Template, pk=template_id)
    
    # Fallback de segurança: Se não tiver config salva, escaneia na hora
    campos = template_db.configuracao_campos
    if not campos:
        tags = extrair_tags_do_docx(template_db.arquivo_template.path)
        campos = [{'tag': t, 'label': t.replace('_',' ').title(), 'tipo': 'text'} for t in tags]

    if request.method == 'POST':
        try:
            doc = DocxTemplate(template_db.arquivo_template.path)
            contexto = {}
            
            # Processa cada campo conforme seu tipo
            for campo in campos:
                tag = campo['tag']
                tipo = campo.get('tipo', 'text')
                
                if tipo == 'image':
                    imagem_enviada = request.FILES.get(tag)
                    if imagem_enviada:
                        # Redimensiona para 160mm (aprox largura da página A4 menos margens)
                        img_obj = InlineImage(doc, imagem_enviada, width=Mm(160))
                        contexto[tag] = img_obj
                    else:
                        contexto[tag] = ""
                
                elif tipo == 'checkbox':
                    # Checkbox envia 'on' ou nada
                    valor = request.POST.get(tag)
                    contexto[tag] = True if valor else False

                elif tipo == 'date':
                    valor = request.POST.get(tag)
                    if valor:
                        try:
                            # Converte YYYY-MM-DD (HTML) para DD/MM/YYYY (BR)
                            data_obj = datetime.strptime(valor, '%Y-%m-%d')
                            contexto[tag] = data_obj.strftime('%d/%m/%Y')
                        except ValueError:
                            contexto[tag] = valor
                    else:
                        contexto[tag] = ""
                
                else:
                    # Text, Textarea, Currency, CPF
                    contexto[tag] = request.POST.get(tag, "")

            # Renderiza o DOCX na memória
            doc.render(contexto)
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            # Salva histórico (Removendo objetos de imagem para não quebrar o JSON)
            dados_log = {k: str(v) for k, v in contexto.items() if not isinstance(v, InlineImage)}
            
            DocumentoGerado.objects.create(
                usuario=request.user,
                template=template_db,
                dados_inputados=dados_log
            )

            # Prepara o download
            filename = f"{template_db.titulo}_{datetime.now().strftime('%Y%m%d%H%M')}.docx"
            response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        except Exception as e:
            messages.error(request, f"Erro ao gerar documento: {str(e)}")
            return redirect('lista_templates')

    return render(request, 'docgen/formulario.html', {'template': template_db, 'campos': campos})

@login_required
def dashboard(request):
    """
    Histórico de Geração.
    Staff/Admin vê tudo. Usuário comum vê só o seu.
    """
    if request.user.is_superuser or request.user.is_staff:
        historico_list = DocumentoGerado.objects.all().order_by('-data_geracao')
    else:
        historico_list = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')
    
    # Aplicando a paginação (15 documentos por página)
    paginator = Paginator(historico_list, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'docgen/dashboard.html', {
        'historico': page_obj,
        'page_obj': page_obj  # Essencial para o componente de paginação aparecer
    })

@login_required
def biblioteca_modelos(request):
    """
    Biblioteca com Busca Server-Side e Paginação.
    """
    # 1. Base
    templates_list = Template.objects.filter(ativo=True)

    # 2. Filtros (Mesma lógica do Catálogo)
    busca = request.GET.get('q')
    setor_id = request.GET.get('setor')
    area_id = request.GET.get('area')
    categoria_id = request.GET.get('categoria')

    if busca:
        templates_list = templates_list.filter(
            Q(titulo__icontains=busca) | Q(descricao__icontains=busca)
        )
    if setor_id and setor_id != 'todos':
        templates_list = templates_list.filter(setor_id=setor_id)
    if area_id and area_id != 'todos':
        templates_list = templates_list.filter(area_id=area_id)
    if categoria_id and categoria_id != 'todos':
        templates_list = templates_list.filter(categoria_id=categoria_id)

    # 3. Ordenação e Paginação
    templates_list = templates_list.order_by('setor__nome', 'area__nome', 'titulo')
    
    paginator = Paginator(templates_list, 15) # 15 itens por página na tabela
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Contexto
    setores = Setor.objects.all().order_by('nome')
    areas = Area.objects.all().order_by('nome')
    categorias = Categoria.objects.all().order_by('nome')
    
    return render(request, 'docgen/biblioteca.html', {
        'templates': page_obj,
        'page_obj': page_obj,
        'setores': setores,
        'areas': areas,
        'categorias': categorias,
        'filtros_atuais': request.GET # Mantém a busca na barra
    })

# ==============================================================================
#  AUTENTICAÇÃO E UTILITÁRIOS
# ==============================================================================

class SignUpView(generic.CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy('login')
    template_name = 'registration/signup.html'

    def form_valid(self, form):
        # Cria usuário inativo por segurança
        user = form.save(commit=False)
        user.is_active = False 
        user.save()
        messages.info(self.request, "✅ Cadastro realizado! Aguarde a liberação do seu acesso pelo administrador.")
        return redirect('login')
    
@login_required
def guia_modelos(request):
    """Página estática de ajuda para criação de modelos."""
    return render(request, 'docgen/guia.html')

@login_required
def lista_templates(request):
    """
    Catálogo com Busca e Paginação no Server-Side.
    Suporta volume infinito de dados sem travar o navegador.
    """
    # 1. Base Query
    templates_list = Template.objects.filter(ativo=True)

    # 2. Aplicação de Filtros (Recebidos via GET)
    busca = request.GET.get('q')
    setor_id = request.GET.get('setor')
    area_id = request.GET.get('area')
    categoria_id = request.GET.get('categoria')

    if busca:
        # Busca no Título OU na Descrição (Insensitive)
        templates_list = templates_list.filter(
            Q(titulo__icontains=busca) | Q(descricao__icontains=busca)
        )
    
    if setor_id and setor_id != 'todos':
        templates_list = templates_list.filter(setor_id=setor_id)
    
    if area_id and area_id != 'todos':
        templates_list = templates_list.filter(area_id=area_id)

    if categoria_id and categoria_id != 'todos':
        templates_list = templates_list.filter(categoria_id=categoria_id)

    # 3. Ordenação
    templates_list = templates_list.order_by('setor__nome', 'area__nome', 'titulo')

    # 4. Paginação (9 por página)
    paginator = Paginator(templates_list, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Listas para os dropdowns
    setores = Setor.objects.all().order_by('nome')
    areas = Area.objects.all().order_by('nome')
    categorias = Categoria.objects.all().order_by('nome')

    # --> LISTA DE FAVORITOS DO USUÁRIO <--
    favoritos_ids = list(TemplateFavorito.objects.filter(usuario=request.user).values_list('template_id', flat=True))
    
    return render(request, 'docgen/lista.html', {
        'templates': page_obj,
        'page_obj': page_obj,
        'setores': setores,
        'areas': areas,
        'categorias': categorias,
        'filtros_atuais': request.GET,
        'favoritos_ids': favoritos_ids
    })

@login_required
@staff_member_required
def gerenciar_usuarios(request):
    """
    Painel customizado para gestão de usuários.
    Permite aprovação, inativação e promoção em lote.
    """
    if request.method == 'POST':
        acao = request.POST.get('acao')
        usuarios_ids = request.POST.getlist('usuarios') # Pega a lista de IDs marcados nos checkboxes

        if not usuarios_ids:
            messages.warning(request, "Nenhum usuário foi selecionado.")
        else:
            # Filtra os usuários selecionados
            usuarios = User.objects.filter(id__in=usuarios_ids)
            
            # Executa a ação escolhida
            if acao == 'aprovar':
                usuarios.update(is_active=True)
                messages.success(request, f"{usuarios.count()} usuário(s) aprovado(s) com sucesso!")
                
            elif acao == 'remover_acesso':
                # Evita que o admin remova o próprio acesso sem querer
                usuarios = usuarios.exclude(id=request.user.id)
                usuarios.update(is_active=False)
                messages.success(request, f"Acesso revogado para {usuarios.count()} usuário(s).")
                
            elif acao == 'promover_admin':
                usuarios.update(is_staff=True)
                messages.success(request, f"{usuarios.count()} usuário(s) promovido(s) a Administrador(es).")
                
            elif acao == 'rebaixar_admin':
                usuarios = usuarios.exclude(id=request.user.id)
                usuarios.update(is_staff=False, is_superuser=False)
                messages.success(request, f"{usuarios.count()} usuário(s) rebaixado(s) a usuário(s) comum(ns).")
                
            elif acao == 'excluir':
                # Remove o próprio usuário da lista de exclusão por segurança
                usuarios = usuarios.exclude(id=request.user.id)
                count = usuarios.count()
                if count > 0:
                    try:
                        usuarios.delete()
                        messages.success(request, f"{count} usuário(s) excluído(s) definitivamente.")
                    except ProtectedError:
                        # Se o usuário já gerou documentos, o banco bloqueia a exclusão por causa do on_delete=models.PROTECT
                        messages.error(request, "Um ou mais usuários selecionados já geraram documentos e não podem ser excluídos para manter o histórico. Recomendamos apenas 'Revogar Acesso'.")

        return redirect('gerenciar_usuarios')

    # Separa os usuários para as abas
    usuarios_pendentes = User.objects.filter(is_active=False).order_by('-date_joined')
    usuarios_ativos = User.objects.filter(is_active=True).order_by('-date_joined')

    return render(request, 'docgen/gerenciar_usuarios.html', {
        'usuarios_pendentes': usuarios_pendentes,
        'usuarios_ativos': usuarios_ativos
    })

@login_required
@staff_member_required
def gerenciar_equipes(request):
    """
    Painel exclusivo para a Coordenação criar e visualizar 
    Equipes, Núcleos e Sub-núcleos do escritório.
    """
    if request.method == 'POST':
        nome = request.POST.get('nome')
        descricao = request.POST.get('descricao')
        equipe_pai_id = request.POST.get('equipe_pai')
        
        if nome:
            try:
                nova_equipe = Equipe.objects.create(
                    nome=nome,
                    descricao=descricao,
                    # Se não selecionar pai, fica None (é uma Equipe Raiz)
                    equipe_pai_id=equipe_pai_id if equipe_pai_id else None 
                )
                # O coordenador que criou a equipe já vira supervisor dela automaticamente
                nova_equipe.supervisores.add(request.user)
                messages.success(request, f"Estrutura '{nome}' criada com sucesso!")
            except Exception as e:
                messages.error(request, f"Erro ao criar equipe: {e}")
                
        return redirect('gerenciar_equipes')

    # Busca todas as equipes para listar e para popular o seletor de Equipe Pai
    equipes = Equipe.objects.all().select_related('equipe_pai').order_by('equipe_pai__nome', 'nome')
    
    return render(request, 'docgen/gerenciar_equipes.html', {
        'equipes': equipes
    })

@login_required
def toggle_favorito(request, template_id):
    """Ativa ou desativa o favorito sem recarregar a página."""
    if request.method == 'POST':
        template = get_object_or_404(Template, id=template_id)
        
        # Tenta pegar se já existe, senão cria
        favorito, created = TemplateFavorito.objects.get_or_create(
            usuario=request.user, 
            template=template
        )
        
        if not created:
            # Se já existia, significa que o usuário clicou para DESFAVORITAR
            favorito.delete()
            return JsonResponse({'status': 'removido'})
        
        # Se foi criado agora, é porque FAVORITOU
        return JsonResponse({'status': 'adicionado'})
        
    return JsonResponse({'erro': 'Método inválido'}, status=400)

@login_required
def minha_biblioteca(request):
    """
    Exibe os modelos favoritados, suportando hierarquia de pastas e 
    pastas compartilhadas via Equipes/Núcleos da MDR Advocacia.
    """
    pasta_id = request.GET.get('pasta')
    
    # 1. Busca as Equipes que o usuário faz parte (para ver pastas compartilhadas)
    equipes_usuario = request.user.equipes_participa.all()

    # 2. Define as pastas do menu lateral (Apenas as Raiz)
    # Mostra pastas do próprio usuário OU compartilhadas com as equipes dele
    pastas_sidebar = PastaPersonalizada.objects.filter(
        (models.Q(usuario=request.user) | models.Q(equipes_permitidas__in=equipes_usuario)),
        pasta_pai__isnull=True
    ).distinct()

    # 3. Busca os Favoritos (Arquivos)
    favoritos_query = TemplateFavorito.objects.filter(usuario=request.user).select_related('template', 'pasta')

    if pasta_id == 'sem_pasta':
        favoritos_query = favoritos_query.filter(pasta__isnull=True)
    elif pasta_id:
        favoritos_query = favoritos_query.filter(pasta_id=pasta_id)

    favoritos_query = favoritos_query.order_by('template__titulo')
    
    # 4. Busca Subpastas (se houver uma pasta selecionada)
    subpastas = []
    if pasta_id and pasta_id != 'sem_pasta':
        subpastas = PastaPersonalizada.objects.filter(pasta_pai_id=pasta_id)

    # 5. Paginação
    paginator = Paginator(favoritos_query, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # --- O CONTEXTO VAI AQUI (A sacola de dados para o HTML) ---
    context = {
        'favoritos': page_obj,
        'page_obj': page_obj,
        'pastas': pastas_sidebar,
        'subpastas': subpastas,
        'pasta_atual_id': pasta_id,
        # Essa linha abaixo é a que permite o modal de compartilhar listar os núcleos:
        'equipes_disponiveis': Equipe.objects.all().order_by('nome'), 
    }

    return render(request, 'docgen/minha_biblioteca.html', context)

@login_required
def criar_pasta(request):
    """Cria uma nova pasta ou subpasta."""
    if request.method == 'POST':
        nome = request.POST.get('nome')
        pai_id = request.POST.get('pasta_pai') # ID da pasta onde você está no momento
        
        if nome:
            nova_pasta = PastaPersonalizada.objects.create(
                usuario=request.user, 
                nome=nome,
                pasta_pai_id=pai_id if pai_id else None
            )
            messages.success(request, f"Pasta '{nome}' criada!")
    
    # Retorna para a pasta de origem para não perder o fluxo
    redirect_url = reverse('minha_biblioteca')
    if pai_id:
        redirect_url += f"?pasta={pai_id}"
        
    return redirect(redirect_url)

@login_required
def mover_para_pasta(request, template_id):
    """Move um template favoritado entre pastas (incluindo subpastas)."""
    if request.method == 'POST':
        try:
            dados = json.loads(request.body)
            nova_pasta_id = dados.get('pasta_id')
            
            favorito = get_object_or_404(TemplateFavorito, template_id=template_id, usuario=request.user)
            
            if not nova_pasta_id or nova_pasta_id == 'nenhuma':
                favorito.pasta = None
            else:
                # Garante que o usuário só mova para pastas que ele tem acesso
                equipes = request.user.equipes_participa.all()
                pasta = get_object_or_404(
                    PastaPersonalizada, 
                    models.Q(id=nova_pasta_id) & (models.Q(usuario=request.user) | models.Q(equipes_permitidas__in=equipes))
                )
                favorito.pasta = pasta
                
            favorito.save()
            return JsonResponse({'status': 'sucesso'})
        except Exception as e:
            return JsonResponse({'erro': str(e)}, status=400)
            
    return JsonResponse({'erro': 'Método inválido'}, status=400)

@login_required
def excluir_pasta(request, pasta_id):
    """Exclui a pasta do usuário. Os modelos dentro dela apenas perdem a referência da pasta."""
    if request.method == 'POST':
        pasta = get_object_or_404(PastaPersonalizada, id=pasta_id, usuario=request.user)
        nome_pasta = pasta.nome
        pasta.delete() # O on_delete=models.SET_NULL no model garante que os templates não sejam apagados
        messages.success(request, f"Pasta '{nome_pasta}' excluída. Os modelos voltaram para 'Sem pasta'.")
    return redirect('minha_biblioteca')

@login_required
def compartilhar_pasta(request):
    """Lógica para vincular uma pasta a múltiplas equipes."""
    if request.method == 'POST':
        pasta_id = request.POST.get('pasta_id')
        equipes_ids = request.POST.getlist('equipes') # Pega todos os checkboxes marcados
        
        pasta = get_object_or_404(PastaPersonalizada, id=pasta_id, usuario=request.user)
        
        # Atualiza as permissões
        pasta.equipes_permitidas.set(equipes_ids)
        messages.success(request, f"Permissões da pasta '{pasta.nome}' atualizadas!")
        
    return redirect('minha_biblioteca')