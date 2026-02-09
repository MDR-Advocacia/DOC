import re
from docx import Document

def extrair_tags_do_docx(caminho_arquivo):
    """
    Abre o arquivo DOCX e retorna as tags na ORDEM EXATA em que aparecem.
    Suporta:
    1. Variáveis de impressão: {{ variavel }}
    2. Condicionais lógicas: {% if variavel %}
    """
    try:
        doc = Document(caminho_arquivo)
        texto_completo = []

        # 1. Varre o corpo do texto (Parágrafos)
        for para in doc.paragraphs:
            texto_completo.append(para.text)

        # 2. Varre todas as tabelas (Linha por linha, Célula por célula)
        # Isso garante que a ordem visual seja respeitada
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    texto_completo.append(cell.text)

        # Junta tudo numa string única preservando a ordem
        conteudo = "\n".join(texto_completo)

        # --- O SEGREDO DO REGEX ---
        # Procura por:
        # (Abertura {{ OU {% if) + (espaços) + (NOME DA VARIÁVEL) + (espaços) + (Fechamento }} OU %})
        pattern = r'(?:\{\{|\{%\s*if)\s*(\w+)\s*(?:\}\}|%\})'
        
        # findall retorna uma lista na ordem encontrada no texto
        tags_encontradas = re.findall(pattern, conteudo)

        # --- REMOVER DUPLICATAS MANTENDO A ORDEM ---
        # set() destrói a ordem. sorted() ordena alfabeticamente.
        # dict.fromkeys() mantém a ordem de inserção (Python 3.7+) e remove duplicatas.
        tags_unicas_ordenadas = list(dict.fromkeys(tags_encontradas))

        return tags_unicas_ordenadas

    except Exception as e:
        print(f"Erro ao ler DOCX: {e}")
        return []