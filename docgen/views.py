# docgen/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
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

# Bibliotecas de processamento de DOCX
from docxtpl import DocxTemplate, InlineImage 
from docx.shared import Mm 
import io
from datetime import datetime

# Seus Models e Utils
from .models import Template, DocumentoGerado, Setor, Categoria, Area
from .utils import extrair_tags_do_docx 

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
    PASSO 2: Tela para definir Labels e Tipos das variáveis encontradas no Word.
    """
    template = get_object_or_404(Template, pk=template_id)
    
    # 1. O Robô lê o arquivo físico e acha as tags {{ ... }}
    tags_encontradas = extrair_tags_do_docx(template.arquivo_template.path)
    
    # 2. Carrega configuração existente (se houver) para manter edições anteriores
    config_atual = template.configuracao_campos or []
    dict_config = {item['tag']: item for item in config_atual}

    # 3. Salvar Configuração (POST)
    if request.method == 'POST':
        nova_configuracao = []
        for tag in tags_encontradas:
            label_input = request.POST.get(f'label_{tag}')
            tipo_input = request.POST.get(f'tipo_{tag}')
            
            nova_configuracao.append({
                "tag": tag,
                "label": label_input or tag.replace('_', ' ').title(),
                "tipo": tipo_input
            })
        
        template.configuracao_campos = nova_configuracao
        template.save()
        messages.success(request, f"Modelo '{template.titulo}' configurado e pronto para uso!")
        return redirect('lista_templates')

    # 4. Exibir (GET) - Mescla tags do arquivo com configurações do banco
    campos_para_exibir = []
    for tag in tags_encontradas:
        dados = dict_config.get(tag, {})
        campos_para_exibir.append({
            'tag': tag,
            'label': dados.get('label', tag.replace('_', ' ').title()),
            'tipo': dados.get('tipo', 'text')
        })

    return render(request, 'docgen/configurar_template.html', {
        'template': template,
        'campos': campos_para_exibir
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
def lista_templates(request):
    """Catálogo de peças com filtros"""
    templates = Template.objects.filter(ativo=True).order_by('setor__nome', 'area__nome', 'titulo')
    setores = Setor.objects.all().order_by('nome')
    areas = Area.objects.all().order_by('nome')
    categorias = Categoria.objects.all().order_by('nome')
    
    return render(request, 'docgen/lista.html', {
        'templates': templates,
        'setores': setores,
        'areas': areas,
        'categorias': categorias
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
        historico = DocumentoGerado.objects.all().order_by('-data_geracao')
    else:
        historico = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')
    
    return render(request, 'docgen/dashboard.html', {'historico': historico})

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
        'setores': setores,
        'areas': areas,
        'categorias': categorias,
        'filtros_atuais': request.GET # Mantém a busca na barra
    })

# ==============================================================================
#  AUTENTICAÇÃO
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
    
    return render(request, 'docgen/lista.html', {
        'templates': page_obj,
        'setores': setores,
        'areas': areas,
        'categorias': categorias,
        # Devolvemos os valores atuais para manter os inputs preenchidos
        'filtros_atuais': request.GET 
    })