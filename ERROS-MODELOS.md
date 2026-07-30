# Catálogo de erros em modelos `.docx`

Lista dos problemas de tag que a pré-validação já reconhece no upload de um modelo.

**Quando aparecer um erro novo que não está aqui:** documente na tabela abaixo e
adicione a regra em [`docgen/template_validacao.py`](docgen/template_validacao.py).
Cada regra vive em `_classificar_conteudo()` (tags `{{ }}`) ou `_classificar_tag()`
(blocos `{% %}`), e ganha um caso no teste de regressão.

Onde a validação roda — os três caminhos que aceitam `.docx`:

| Caminho | View |
|---|---|
| Upload manual | `criar_template` |
| Sugestão por IA | `sugerir_template_ia` |
| Troca do arquivo base | `editar_template` |

Reprovou, nada é salvo: o modelo não é criado e, na edição, o arquivo antigo
continua no ar intacto.

---

## Erros — bloqueiam o upload

| Tipo | Exemplo errado | Correto | Por que quebra |
|---|---|---|---|
| `hifen` | `{{ e-mail }}` | `{{ e_mail }}` | O `-` é lido como subtração: o Jinja procura as variáveis `e` e `mail`. Falha com `'e' is undefined`. **Sintaxe válida**, então só estoura na geração — foi o caso dos modelos do BB. |
| `ponto` | `{{ N.º_CNJ }}` | `{{ N_CNJ }}` | O `.` é lido como acesso a atributo: procura a variável `N` e nela o campo `º_CNJ`. Falha com `'N' is undefined`. |
| `espaco` | `{{ endereco eletronico }}` | `{{ endereco_eletronico }}` | O parser para no primeiro espaço. Erro de sintaxe: `expected token 'end of print statement'`. |
| `comeca_com_numero` | `{{ 2_via }}` | `{{ via_2 }}` | Nome de variável não pode começar com dígito. |
| `caractere_invalido` | `{{ valor(R$) }}` | `{{ valor_total }}` | Só letras, números e `_` são aceitos no nome do campo. |
| `vazia` | `{{ }}` | — | Não há o que preencher. |
| `chave_desbalanceada` | `{{ nome_cliente` | `{{ nome_cliente }}` | Faltou fechar. Todo o texto seguinte deixa de ser lido como texto. |
| `bloco_desbalanceado` | `{% if x` | `{% if x %}` | Idem para blocos. |
| `bloco_desconhecido` | `{% endiv %}` | `{% endif %}` | Instrução inexistente — normalmente erro de digitação. |
| `bloco_nao_fechado` | `{% if x %}` sem `{% endif %}` | fechar o bloco | Erro de sintaxe: `unexpected end of template`. |
| `fechamento_sobrando` | `{% endif %}` sem `{% if %}` | remover | Sobra de edição anterior. |

## Avisos — não bloqueiam

| Tipo | Exemplo | Observação |
|---|---|---|
| `acento` | `{{ endereço }}` | O sistema renomeia sozinho no upload (`normalize_jinja_tags_in_docx`), porque o Word fragmenta palavras acentuadas no XML e a tag chega quebrada. Melhor já subir sem acento. |
| `chave_simples` | `{ nome_cliente }` | Parece campo com uma chave só. Chave simples é rara em peça jurídica, mas é heurística — por isso é aviso, não erro. |

## Rede de segurança

Além do catálogo, todo arquivo passa por uma **simulação de geração**
(`_simular_geracao`): o template é renderizado com todos os campos vazios,
exatamente como na geração real. Isso pega qualquer defeito que as regras acima
não previram. Se a simulação falhar, o upload é recusado mesmo sem nenhuma regra
ter disparado — é o que garante que nada quebrado entre no catálogo.

## Sobre "em que página está o erro"

O `.docx` **não guarda** a paginação: o Word calcula na hora de renderizar.
Só dá para estimar a página quando o arquivo tem marcadores de quebra
(`lastRenderedPageBreak`, gravado pelo Word ao salvar, ou quebra manual
`<w:br w:type="page"/>`). Muitos arquivos não têm nenhum dos dois — os do BB,
por exemplo, têm zero.

Por isso o relatório sempre mostra o **número do parágrafo**, o **local**
(corpo, tabela com linha/coluna, cabeçalho, rodapé) e o **trecho do texto** para
Ctrl+F no Word. A página aparece só quando é possível calcular, e é aproximada.

Página exata exigiria um motor de layout (LibreOffice headless, ~400 MB na
imagem Docker) — não compensa.

---

## Casos reais já encontrados

| Data | Modelo | Erro | Onde |
|---|---|---|---|
| 2026-07-30 | `PETIÇÃO INICIAL - EXECUÇÃO` (4 cadastros do BB) | `hifen` — `{{ e-mail }}`, `{{ e-mail_2 }}`, `{{ e-mail_3 }}`, `{{ e-mail_fiador2 }}`, `{{ e-mail_fiador3 }}` | Parágrafos 6, 9, 12, 18, 21 — trecho "endereço eletrônico:" |
| — | `PASEP_Base.docx` | `ponto` — `{{ N.º_CNJ }}` | corpo |
