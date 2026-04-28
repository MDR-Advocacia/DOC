TRIBUNAIS_ESTADUAIS = {
    '8.01': 'Acre',
    '8.02': 'Alagoas',
    '8.03': 'Amapa',
    '8.04': 'Amazonas',
    '8.05': 'Bahia',
    '8.06': 'Ceara',
    '8.07': 'Distrito Federal',
    '8.08': 'Espirito Santo',
    '8.09': 'Goias',
    '8.10': 'Maranhao',
    '8.11': 'Mato Grosso',
    '8.12': 'Mato Grosso do Sul',
    '8.13': 'Minas Gerais',
    '8.14': 'Para',
    '8.15': 'Paraiba',
    '8.16': 'Parana',
    '8.17': 'Pernambuco',
    '8.18': 'Piaui',
    '8.19': 'Rio de Janeiro',
    '8.20': 'Rio Grande do Norte',
    '8.21': 'Rio Grande do Sul',
    '8.22': 'Rondonia',
    '8.23': 'Roraima',
    '8.24': 'Santa Catarina',
    '8.25': 'Sao Paulo',
    '8.26': 'Sergipe',
    '8.27': 'Tocantins',
}


COLUNAS_OBRIGATORIAS_PROCESSOS = [
    {
        'nome': 'numero_processo',
        'descricao': 'Numero CNJ do processo.',
    },
    {
        'nome': 'usuario_email',
        'descricao': 'Email do usuario dono do processo no DOC.',
    },
]


COLUNAS_OPCIONAIS_PROCESSOS = [
    {
        'nome': 'observacao',
        'descricao': 'Observacao livre para o processo.',
    },
    {
        'nome': 'referencia_interna',
        'descricao': 'Identificador interno opcional do escritorio.',
    },
]


PROCESSOS_STATUS_CANONICOS = [
    'PENDENTE',
    'EM_FILA',
    'PROCESSANDO',
    'BAIXADO',
    'PROCESSO_NAO_ENCONTRADO',
    'PETICAO_NAO_LOCALIZADA',
    'FALHA_TECNICA',
]
