import re
from pathlib import Path

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

# --- Tabela para as Categorias (NOVO) ---
class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.nome

class Setor(models.Model):
    nome = models.CharField(max_length=50, unique=True)
    
    def __str__(self):
        return self.nome

class Area(models.Model):
    setor = models.ForeignKey(Setor, on_delete=models.CASCADE, related_name='areas')
    nome = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.nome} ({self.setor.nome})"

class Template(models.Model):
    titulo = models.CharField(max_length=200, verbose_name="Título da Peça")
    descricao = models.TextField(blank=True, verbose_name="Descrição/Instruções")
    
    setor = models.ForeignKey(Setor, on_delete=models.PROTECT, verbose_name="Setor")
    area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Área")
    
    # --- CAMPO NOVO QUE ESTAVA FALTANDO ---
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Tipo de Documento")
    
    arquivo_template = models.FileField(upload_to='templates/')
    configuracao_campos = models.JSONField(default=list, verbose_name="Configuração dos Campos")
    
    data_criacao = models.DateTimeField(auto_now_add=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.titulo

class DocumentoGerado(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.PROTECT)
    template = models.ForeignKey(Template, on_delete=models.PROTECT)
    dados_inputados = models.JSONField()
    arquivo_final = models.FileField(upload_to='gerados/', blank=True, null=True)
    data_geracao = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.template.titulo} - {self.usuario.username}"

# ==========================================
# NOVOS MODELOS: MINHA BIBLIOTECA E FAVORITOS
# ==========================================

class Equipe(models.Model):
    """
    Representa os Grupos e Núcleos. 
    Se tiver uma 'equipe_pai', ele atua como um sub-núcleo.
    """
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True, null=True)
    
    # Auto-referência: Permite criar "Núcleo Banco do Brasil" dentro de "Equipe Trabalhista"
    equipe_pai = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='sub_equipes')
    
    # Supervisores gerenciam a equipe. Membros apenas consomem.
    supervisores = models.ManyToManyField(User, related_name='equipes_gerenciadas')
    membros = models.ManyToManyField(User, related_name='equipes_participa', blank=True)
    
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        if self.equipe_pai:
            return f"{self.equipe_pai.nome} > {self.nome}"
        return self.nome


class PastaPersonalizada(models.Model):
    """Pastas da biblioteca (agora suportam subpastas e compartilhamento em lote)."""
    ESCOPO_BIBLIOTECA = 'biblioteca'
    ESCOPO_REPOSITORIO = 'repositorio'
    ESCOPO_CHOICES = [
        (ESCOPO_BIBLIOTECA, 'Biblioteca'),
        (ESCOPO_REPOSITORIO, 'Repositorio'),
    ]

    ACESSO_PRIVADO = 'privado'
    ACESSO_EQUIPES = 'equipes'
    ACESSO_RESTRITO = 'restrito'
    ACESSO_CHOICES = [
        (ACESSO_PRIVADO, 'Privada'),
        (ACESSO_EQUIPES, 'Equipes'),
        (ACESSO_RESTRITO, 'Usuarios selecionados'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas_criadas')
    nome = models.CharField(max_length=100)
    escopo = models.CharField(max_length=20, choices=ESCOPO_CHOICES, default=ESCOPO_BIBLIOTECA)
    
    # Auto-referência: Permite criar Pastas dentro de Pastas
    pasta_pai = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subpastas')
    
    # Lógica de Compartilhamento
    compartilhada = models.BooleanField(default=False)
    nivel_acesso = models.CharField(max_length=20, choices=ACESSO_CHOICES, default=ACESSO_PRIVADO)
    equipes_permitidas = models.ManyToManyField(Equipe, blank=True, related_name='pastas_acessiveis')
    usuarios_permitidos = models.ManyToManyField(User, blank=True, related_name='pastas_com_acesso')
    
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        indexes = [
            models.Index(fields=['escopo', 'usuario'], name='docgen_pasta_esc_usuario_idx'),
            models.Index(fields=['escopo', 'nivel_acesso'], name='docgen_pasta_esc_acesso_idx'),
        ]

    def __str__(self):
        if self.pasta_pai:
            return f"{self.pasta_pai.nome} / {self.nome}"
        return self.nome


class TemplateFavorito(models.Model):
    """Ligação entre o usuário (ou a equipe), o modelo e a pasta onde ele está guardado."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favoritos')
    template = models.ForeignKey(Template, on_delete=models.CASCADE)
    pasta = models.ForeignKey(PastaPersonalizada, on_delete=models.SET_NULL, null=True, blank=True, related_name='templates')
    adicionado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['usuario', 'template'] 

    def __str__(self):
        return f"{self.usuario.username} favoritou {self.template.titulo}"


class ProcessoStatus(models.TextChoices):
    PENDENTE = 'PENDENTE', 'Pendente'
    EM_FILA = 'EM_FILA', 'Em fila'
    PROCESSANDO = 'PROCESSANDO', 'Processando'
    BAIXADO = 'BAIXADO', 'Baixado'
    PROCESSO_NAO_ENCONTRADO = 'PROCESSO_NAO_ENCONTRADO', 'Processo nao encontrado'
    PETICAO_NAO_LOCALIZADA = 'PETICAO_NAO_LOCALIZADA', 'Peticao inicial nao localizada'
    FALHA_TECNICA = 'FALHA_TECNICA', 'Falha tecnica'


class TipoArquivoProcesso(models.TextChoices):
    PETICAO_INICIAL = 'peticao_inicial', 'Peticao inicial'


def _upload_lote_processos(instance, filename):
    extensao = Path(filename or '').suffix.lower() or '.csv'
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    return f"processos/lotes/lote_{instance.usuario_id}_{timestamp}{extensao}"


def _upload_arquivo_processo(instance, filename):
    numero_cnj = re.sub(r'[^0-9]', '', instance.processo.numero_cnj or '') or 'processo'
    extensao = Path(filename or '').suffix.lower() or '.pdf'
    nome_base = instance.tipo or 'arquivo'
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    return (
        f"processos/{instance.processo.usuario_id}/{numero_cnj}/"
        f"{nome_base}_{timestamp}{extensao}"
    )


class LoteImportacaoProcessos(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name='lotes_importacao_processos')
    arquivo_planilha = models.FileField(upload_to=_upload_lote_processos)
    total_linhas = models.PositiveIntegerField(default=0)
    total_validas = models.PositiveIntegerField(default=0)
    total_invalidas = models.PositiveIntegerField(default=0)
    total_processos_criados = models.PositiveIntegerField(default=0)
    total_processos_atualizados = models.PositiveIntegerField(default=0)
    resultado_importacao = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f"Lote #{self.pk} - {self.usuario.username}"


class Processo(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='processos')
    numero_cnj = models.CharField(max_length=25)
    tribunal_codigo = models.CharField(max_length=4)
    tribunal_nome = models.CharField(max_length=100)
    status_atual = models.CharField(
        max_length=40,
        choices=ProcessoStatus.choices,
        default=ProcessoStatus.PENDENTE,
    )
    ultima_mensagem = models.TextField(blank=True)
    observacao = models.TextField(blank=True)
    referencia_interna = models.CharField(max_length=120, blank=True)
    ultimo_sucesso_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-atualizado_em']
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'numero_cnj'], name='uniq_processo_usuario_numero_cnj'),
        ]
        indexes = [
            models.Index(fields=['status_atual', 'tribunal_codigo']),
        ]

    def __str__(self):
        return f"{self.numero_cnj} - {self.usuario.username}"

    @property
    def arquivo_peticao_atual(self):
        return self.arquivos.filter(
            tipo=TipoArquivoProcesso.PETICAO_INICIAL,
            atual=True,
        ).first()


class ExecucaoCapturaProcesso(models.Model):
    lote = models.ForeignKey(
        LoteImportacaoProcessos,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='execucoes',
    )
    processo = models.ForeignKey(Processo, on_delete=models.CASCADE, related_name='execucoes')
    status = models.CharField(
        max_length=40,
        choices=ProcessoStatus.choices,
        default=ProcessoStatus.PENDENTE,
    )
    worker_id = models.CharField(max_length=120, blank=True)
    tentativa = models.PositiveIntegerField(default=0)
    iniciada_em = models.DateTimeField(null=True, blank=True)
    finalizada_em = models.DateTimeField(null=True, blank=True)
    heartbeat_em = models.DateTimeField(null=True, blank=True)
    mensagem = models.TextField(blank=True)
    tribunal_url = models.URLField(max_length=500, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['status', 'criado_em']),
        ]

    def __str__(self):
        return f"Execucao #{self.pk} - {self.processo.numero_cnj}"


class ArquivoProcesso(models.Model):
    processo = models.ForeignKey(Processo, on_delete=models.CASCADE, related_name='arquivos')
    execucao = models.ForeignKey(
        ExecucaoCapturaProcesso,
        on_delete=models.CASCADE,
        related_name='arquivos',
    )
    tipo = models.CharField(
        max_length=40,
        choices=TipoArquivoProcesso.choices,
        default=TipoArquivoProcesso.PETICAO_INICIAL,
    )
    arquivo = models.FileField(upload_to=_upload_arquivo_processo)
    atual = models.BooleanField(default=True)
    checksum = models.CharField(max_length=64, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        constraints = [
            models.UniqueConstraint(
                fields=['processo', 'tipo'],
                condition=models.Q(atual=True),
                name='uniq_arquivo_processo_atual_por_tipo',
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.processo.numero_cnj}"


def _upload_arquivo_armazenado(instance, filename):
    """Path: arquivos/<user_id>/YYYY-MM/<filename>."""
    return f"arquivos/{instance.usuario_id or 'anon'}/{timezone.now():%Y-%m}/{filename}"


class ArquivoArmazenado(models.Model):
    """Arquivos PDF/XLSX/CSV armazenados pelos usuarios para consulta posterior.

    Diferente de DocumentoGerado (que e saida do gerador) e ArquivoProcesso (que e
    captura de peticao inicial), este e um repositorio livre: o usuario sobe arquivos
    de referencia, planilhas, documentos diversos para consulta e download.
    """

    TIPO_PDF = 'pdf'
    TIPO_XLSX = 'xlsx'
    TIPO_CSV = 'csv'
    TIPO_OUTRO = 'outro'
    TIPO_CHOICES = [
        (TIPO_PDF, 'PDF'),
        (TIPO_XLSX, 'Excel (XLSX)'),
        (TIPO_CSV, 'CSV'),
        (TIPO_OUTRO, 'Outro'),
    ]

    arquivo = models.FileField(upload_to=_upload_arquivo_armazenado)
    nome_original = models.CharField(max_length=255)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=TIPO_OUTRO)
    descricao = models.TextField(blank=True)
    pasta = models.ForeignKey(
        PastaPersonalizada,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='arquivos',
    )
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='arquivos_armazenados',
    )
    tamanho_bytes = models.PositiveBigIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['usuario', '-criado_em'], name='docgen_arq_usuario_29a1b6_idx'),
            models.Index(fields=['tipo'], name='docgen_arq_tipo_2cd9f4_idx'),
        ]

    def __str__(self):
        return self.nome_original or f"Arquivo #{self.pk}"

    @property
    def tamanho_humano(self):
        size = self.tamanho_bytes
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @classmethod
    def detectar_tipo(cls, filename):
        ext = (filename or '').lower().rsplit('.', 1)[-1]
        if ext == 'pdf':
            return cls.TIPO_PDF
        if ext == 'xlsx':
            return cls.TIPO_XLSX
        if ext == 'csv':
            return cls.TIPO_CSV
        return cls.TIPO_OUTRO
