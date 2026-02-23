from django.db import models
from django.contrib.auth.models import User

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
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas_criadas')
    nome = models.CharField(max_length=100)
    
    # Auto-referência: Permite criar Pastas dentro de Pastas
    pasta_pai = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subpastas')
    
    # Lógica de Compartilhamento
    compartilhada = models.BooleanField(default=False)
    equipes_permitidas = models.ManyToManyField(Equipe, blank=True, related_name='pastas_acessiveis')
    
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']

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