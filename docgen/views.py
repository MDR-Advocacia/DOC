from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
# Importamos todos os modelos necessários
from .models import Template, DocumentoGerado, Setor, Categoria, Area
from docxtpl import DocxTemplate, InlineImage 
from docx.shared import Mm 
import io
from datetime import datetime
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse_lazy
from django.views import generic
from django.contrib import messages 
from django.db.models import Count
from django.db.models.functions import TruncMonth

@login_required
def lista_templates(request):
    """Tela inicial: Lista todas as peças disponíveis com filtros avançados"""
    # Ordenamos por Setor > Área > Título para ficar organizado visualmente
    templates = Template.objects.filter(ativo=True).order_by('setor__nome', 'area__nome', 'titulo')
    
    # Buscamos todas as opções para os filtros
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
    """Tela do Formulário e Processamento do Word"""
    template_db = get_object_or_404(Template, pk=template_id)
    campos = template_db.configuracao_campos

    if request.method == 'POST':
        # 1. Carregamos o template do Word
        doc = DocxTemplate(template_db.arquivo_template.path)
        
        contexto = {}
        
        # 2. Processamos cada campo
        for campo in campos:
            tag = campo['tag']
            
            if campo['tipo'] == 'image':
                imagem_enviada = request.FILES.get(tag)
                if imagem_enviada:
                    # Mm(160) = 16cm de largura
                    img_obj = InlineImage(doc, imagem_enviada, width=Mm(160))
                    contexto[tag] = img_obj
                else:
                    contexto[tag] = ""
            
            elif campo['tipo'] == 'checkbox':
                valor = request.POST.get(tag)
                contexto[tag] = True if valor else False

            elif campo['tipo'] == 'date':
                valor = request.POST.get(tag)
                if valor:
                    try:
                        data_obj = datetime.strptime(valor, '%Y-%m-%d')
                        contexto[tag] = data_obj.strftime('%d/%m/%Y')
                    except ValueError:
                        contexto[tag] = valor
                else:
                    contexto[tag] = ""

            else:
                contexto[tag] = request.POST.get(tag)

        # 3. Renderiza o documento
        doc.render(contexto)
        
        # 4. Salva na memória
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        # 5. Salva o histórico
        dados_log = {k: str(v) for k, v in contexto.items() if not isinstance(v, InlineImage)}
        
        DocumentoGerado.objects.create(
            usuario=request.user,
            template=template_db,
            dados_inputados=dados_log
        )

        # 6. Envia para download
        filename = f"{template_db.titulo}_{datetime.now().strftime('%Y%m%d%H%M')}.docx"
        response = HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    return render(request, 'docgen/formulario.html', {'template': template_db, 'campos': campos})

@login_required
def dashboard(request):
    """
    Lista o histórico.
    - Se for Admin/Staff: Vê o histórico de TODOS.
    - Se for Usuário Comum: Vê apenas os SEUS documentos.
    """
    
    # Verifica se é Superusuário ou da Equipe (Staff)
    if request.user.is_superuser or request.user.is_staff:
        # Traz tudo (Admin vê geral)
        historico = DocumentoGerado.objects.all().order_by('-data_geracao')
    else:
        # Filtra apenas pelo usuário logado (Segurança)
        historico = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')
    
    return render(request, 'docgen/dashboard.html', {'historico': historico})

@login_required
def biblioteca_modelos(request):
    """Repositório para download direto dos arquivos .docx originais."""
    templates = Template.objects.filter(ativo=True).order_by('setor__nome', 'area__nome', 'titulo')
    
    # Buscamos as opções para os filtros
    setores = Setor.objects.all().order_by('nome')
    categorias = Categoria.objects.all().order_by('nome')
    areas = Area.objects.all().order_by('nome') # <--- NOVIDADE
    
    return render(request, 'docgen/biblioteca.html', {
        'templates': templates,
        'setores': setores,
        'categorias': categorias,
        'areas': areas, # <--- Enviando para o template
    })

# --- CLASSE DE CADASTRO COM TRAVA DE SEGURANÇA ---
class SignUpView(generic.CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy('login')
    template_name = 'registration/signup.html'

    def form_valid(self, form):
        # 1. Pega o usuário, mas não salva no banco ainda
        user = form.save(commit=False)
        
        # 2. TRAVA: Define como INATIVO para impedir login imediato
        user.is_active = False 
        
        # 3. Salva no banco
        user.save()
        
        # 4. Envia mensagem de sucesso para a tela de Login
        messages.info(self.request, "✅ Cadastro realizado com sucesso! Sua conta está aguardando liberação do administrador.")
        
        return redirect('login')
    
@login_required
def home_dashboard(request):
    """Tela inicial com gráficos e indicadores (Landing Page)"""
    
    # 1. Totais Gerais (Cards do topo)
    total_docs = DocumentoGerado.objects.count()
    total_templates = Template.objects.filter(ativo=True).count()
    
    # 2. Dados para Gráfico: Documentos por Setor (Pizza/Donut)
    # Ex: [{'template__setor__nome': 'Trabalhista', 'qtd': 10}, ...]
    docs_por_setor = DocumentoGerado.objects.values('template__setor__nome')\
        .annotate(qtd=Count('id')).order_by('-qtd')
    
    labels_setor = [item['template__setor__nome'] for item in docs_por_setor]
    data_setor = [item['qtd'] for item in docs_por_setor]

    # 3. Dados para Gráfico: Produção Mensal (Linha/Barra)
    # Agrupa por mês de criação
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