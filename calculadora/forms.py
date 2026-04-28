from decimal import Decimal

from django import forms
from django.utils import timezone


def _normalize_decimal_input(value):
    if value in (None, ''):
        return value
    if isinstance(value, Decimal):
        return value

    text = str(value).strip()
    if ',' in text and '.' in text:
        if text.rfind(',') > text.rfind('.'):
            text = text.replace('.', '').replace(',', '.')
        else:
            text = text.replace(',', '')
    elif ',' in text:
        text = text.replace('.', '').replace(',', '.')
    return text


class BRDecimalField(forms.DecimalField):
    def to_python(self, value):
        return super().to_python(_normalize_decimal_input(value))


class SentencaExtracaoForm(forms.Form):
    titulo = forms.CharField(
        max_length=200,
        required=False,
        label='Titulo interno',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Condenacao Maria x Banco X'}),
    )
    texto_sentenca = forms.CharField(
        label='Sentenca',
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 16,
                'placeholder': 'Cole aqui o texto integral ou os trechos relevantes da sentenca.',
            }
        ),
    )
    arquivo_sentenca_pdf = forms.FileField(
        required=False,
        label='PDF da sentenca',
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.pdf,application/pdf',
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        texto_sentenca = (cleaned_data.get('texto_sentenca') or '').strip()
        arquivo_sentenca_pdf = cleaned_data.get('arquivo_sentenca_pdf')

        if not texto_sentenca and not arquivo_sentenca_pdf:
            raise forms.ValidationError('Informe o texto da sentenca ou envie um PDF para extracao.')

        if arquivo_sentenca_pdf and not arquivo_sentenca_pdf.name.lower().endswith('.pdf'):
            self.add_error('arquivo_sentenca_pdf', 'Envie um arquivo PDF valido.')

        cleaned_data['texto_sentenca'] = texto_sentenca
        return cleaned_data


class ParametrosCalculoForm(forms.Form):
    valor_principal = BRDecimalField(label='Valor principal', max_digits=14, decimal_places=2, min_value=Decimal('0.00'))
    correcao_percentual = BRDecimalField(
        label='Correcao monetaria acumulada (%)',
        max_digits=8,
        decimal_places=4,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('0.00'),
    )
    indice_correcao = forms.CharField(
        label='Indice de correcao',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: INPC, IPCA-E, SELIC'}),
    )
    data_termo_inicial_correcao = forms.DateField(
        label='Termo inicial da correcao',
        required=False,
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    juros_mensais_percentual = BRDecimalField(
        label='Juros moratorios (% ao mes)',
        max_digits=8,
        decimal_places=4,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('1.00'),
    )
    data_termo_inicial_juros = forms.DateField(
        label='Termo inicial dos juros',
        required=False,
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    data_base_calculo = forms.DateField(
        label='Data-base do calculo',
        required=False,
        initial=timezone.localdate,
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    honorarios_percentual = BRDecimalField(
        label='Honorarios (%)',
        max_digits=8,
        decimal_places=4,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('0.00'),
    )
    multa_percentual = BRDecimalField(
        label='Multa (%)',
        max_digits=8,
        decimal_places=4,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('0.00'),
    )
    outros_acrescimos = BRDecimalField(
        label='Outros acrescimos',
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('0.00'),
    )
    descontos = BRDecimalField(
        label='Descontos',
        max_digits=14,
        decimal_places=2,
        min_value=Decimal('0.00'),
        required=False,
        initial=Decimal('0.00'),
    )
    observacoes_calculo = forms.CharField(
        label='Observacoes do calculo',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not getattr(field.widget, 'attrs', None):
                field.widget.attrs = {}
            field.widget.attrs.setdefault('class', 'form-control')
