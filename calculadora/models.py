from django.contrib.auth.models import User
from django.db import models


class CalculoCondenacaoCivel(models.Model):
    STATUS_RASCUNHO = 'rascunho'
    STATUS_EXTRAIDO = 'extraido'
    STATUS_CALCULADO = 'calculado'
    STATUS_ERRO = 'erro'

    STATUS_CHOICES = [
        (STATUS_RASCUNHO, 'Rascunho'),
        (STATUS_EXTRAIDO, 'Parametros extraidos'),
        (STATUS_CALCULADO, 'Calculado'),
        (STATUS_ERRO, 'Erro'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.PROTECT, related_name='calculos_civeis')
    titulo = models.CharField(max_length=200, blank=True)
    arquivo_sentenca_pdf = models.FileField(upload_to='calculadora/sentencas_pdf/%Y/%m/', blank=True)
    texto_sentenca = models.TextField()
    parametros_extraidos = models.JSONField(default=dict, blank=True)
    parametros_confirmados = models.JSONField(default=dict, blank=True)
    resultado_calculo = models.JSONField(default=dict, blank=True)
    memoria_calculo = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RASCUNHO)
    provedor_extracao = models.CharField(max_length=100, blank=True)
    modelo_extracao = models.CharField(max_length=100, blank=True)
    observacoes_extracao = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-atualizado_em']
        verbose_name = 'Calculo de Condenacao Civel'
        verbose_name_plural = 'Calculos de Condenacao Civel'

    def __str__(self):
        return self.titulo or f"Calculo civel #{self.pk}"
