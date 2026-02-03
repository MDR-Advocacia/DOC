from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
# Importamos Template, DocumentoGerado e agora o SETOR também
from .models import Template, DocumentoGerado, Setor
from docxtpl import DocxTemplate, InlineImage 
from docx.shared import Mm 
import io
from datetime import datetime

@login_required
def lista_templates(request):
    """Tela inicial: Lista todas as peças disponíveis e os Setores para filtro"""
    templates = Template.objects.filter(ativo=True)
    setores = Setor.objects.all() # <--- Necessário para o filtro funcionar
    
    return render(request, 'docgen/lista.html', {
        'templates': templates,
        'setores': setores
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
            
            # --- LÓGICA PARA IMAGENS ---
            if campo['tipo'] == 'image':
                imagem_enviada = request.FILES.get(tag)
                if imagem_enviada:
                    # Mm(160) = 16cm de largura
                    img_obj = InlineImage(doc, imagem_enviada, width=Mm(160))
                    contexto[tag] = img_obj
                else:
                    contexto[tag] = ""
            
            # --- LÓGICA PARA CHECKBOX ---
            elif campo['tipo'] == 'checkbox':
                valor = request.POST.get(tag)
                contexto[tag] = True if valor else False

            # --- LÓGICA PARA DATAS ---
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

            # --- LÓGICA PARA TEXTO PADRÃO ---
            else:
                contexto[tag] = request.POST.get(tag)

        # 3. Renderiza o documento
        doc.render(contexto)
        
        # 4. Salva na memória
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        # 5. Salva o histórico (sem objetos de imagem)
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
    """Lista o histórico de documentos gerados pelo usuário"""
    historico = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')
    return render(request, 'docgen/dashboard.html', {'historico': historico})

@login_required
def biblioteca_modelos(request):
    """
    Repositório para download direto dos arquivos .docx originais.
    """
    # Buscamos todos os ativos, ordenados por Setor e depois por Título
    templates = Template.objects.filter(ativo=True).order_by('setor__nome', 'titulo')
    setores = Setor.objects.all()
    
    return render(request, 'docgen/biblioteca.html', {
        'templates': templates,
        'setores': setores
    })