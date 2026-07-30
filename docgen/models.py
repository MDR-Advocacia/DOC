import re
from pathlib import Path

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


# Helpers retidos para a migration histórica 0005 conseguir importá-los.
# O módulo de processos foi removido; estas funções não são mais usadas em runtime.
def _upload_lote_processos(instance, filename):  # pragma: no cover
    return f"processos/lotes/{filename}"


def _upload_arquivo_processo(instance, filename):  # pragma: no cover
    return f"processos/arquivos/{filename}"


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

    # Quem subiu o modelo. Null nos modelos criados antes deste campo existir
    # (e se o usuário for removido depois) — nesse caso só o staff gerencia.
    criado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='templates_criados',
        verbose_name="Criado por",
    )

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
    
    # Lógica de Compartilhamento — derivada de `nivel_acesso`.
    # `compartilhada` (legado) foi removido; use `pasta.nivel_acesso != ACESSO_PRIVADO`.
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


def _upload_arquivo_armazenado(instance, filename):
    """Path: arquivos/<user_id>/YYYY-MM/<filename>."""
    return f"arquivos/{instance.usuario_id or 'anon'}/{timezone.now():%Y-%m}/{filename}"


class ArquivoArmazenado(models.Model):
    """Repositório livre de arquivos (PDF/XLSX/CSV) que o usuário sobe para consulta posterior.

    Diferente de DocumentoGerado (saída do gerador de documentos).
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
