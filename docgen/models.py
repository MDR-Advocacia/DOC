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

class PastaPersonalizada(models.Model):
    """Pastas que cada usuário cria para organizar seus modelos favoritos."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pastas')
    nome = models.CharField(max_length=100)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nome']
        # Impede que o mesmo usuário tenha duas pastas com o exato mesmo nome
        unique_together = ['usuario', 'nome'] 

    def __str__(self):
        return self.nome

class TemplateFavorito(models.Model):
    """Tabela de ligação que diz qual template o usuário favoritou e em qual pasta está."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favoritos')
    template = models.ForeignKey(Template, on_delete=models.CASCADE)
    pasta = models.ForeignKey(PastaPersonalizada, on_delete=models.SET_NULL, null=True, blank=True, related_name='templates')
    adicionado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Impede que o usuário favorite o mesmo modelo duas vezes
        unique_together = ['usuario', 'template'] 

    def __str__(self):
        return f"{self.usuario.username} favoritou {self.template.titulo}"