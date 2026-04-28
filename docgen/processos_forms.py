from django import forms
from django.core.exceptions import ValidationError

from .processos_services import parsear_planilha_processos


class ImportarLoteProcessosForm(forms.Form):
    planilha = forms.FileField(
        label="Planilha de processos",
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.xlsx,.csv',
            }
        ),
    )
    confirmar_importacao = forms.BooleanField(
        label="Confirmo que revisei a planilha e quero enfileirar os processos para captura da peticao inicial.",
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        planilha = cleaned_data.get('planilha')
        if not planilha:
            return cleaned_data

        try:
            cleaned_data['dados_planilha'] = parsear_planilha_processos(planilha)
        except ValidationError as exc:
            self.add_error('planilha', exc)
        except Exception as exc:
            self.add_error('planilha', str(exc))

        return cleaned_data
