import re
from docx import Document

def extrair_tags_do_docx(caminho_arquivo):
    """
    Abre o arquivo DOCX e retorna uma lista limpa de todas as tags
    encontradas no formato Jinja2: {{ variavel }}
    """
    try:
        doc = Document(caminho_arquivo)
        texto_completo = []

        # 1. Varre todos os parágrafos de texto
        for para in doc.paragraphs:
            texto_completo.append(para.text)

        # 2. Varre todas as tabelas (importante para petições)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    texto_completo.append(cell.text)
        
        # Junta tudo numa string só para aplicar o Regex
        conteudo = "\n".join(texto_completo)

        # Regex: Procura por {{ espaco? palavra espaco? }}
        # Ex: Pega {{nome}}, {{ nome }}, {{  cpf  }}
        tags_encontradas = re.findall(r'\{\{\s*(\w+)\s*\}\}', conteudo)

        # Remove duplicatas e retorna lista ordenada
        return sorted(list(set(tags_encontradas)))

    except Exception as e:
        print(f"Erro ao ler DOCX: {e}")
        return []