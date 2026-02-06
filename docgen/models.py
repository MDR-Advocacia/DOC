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
    
