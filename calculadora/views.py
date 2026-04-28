from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ParametrosCalculoForm, SentencaExtracaoForm
from .models import CalculoCondenacaoCivel
from .services import (
    calculate_civil_condemnation,
    calculation_form_initial,
    extract_civil_parameters,
    extract_text_from_pdf,
)


def _get_calculo_for_user(user, calculo_id):
    queryset = CalculoCondenacaoCivel.objects.all()
    if not user.is_staff and not user.is_superuser:
        queryset = queryset.filter(usuario=user)
    return get_object_or_404(queryset, id=calculo_id)


@login_required
def lista_calculos(request):
    calculos = CalculoCondenacaoCivel.objects.select_related('usuario')
    if not request.user.is_staff and not request.user.is_superuser:
        calculos = calculos.filter(usuario=request.user)

    paginator = Paginator(calculos, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(
        request,
        'calculadora/lista.html',
        {
            'page_obj': page_obj,
            'calculos': page_obj,
        },
    )


@login_required
def novo_calculo(request):
    if request.method == 'POST':
        form = SentencaExtracaoForm(request.POST, request.FILES)
        if form.is_valid():
            texto_sentenca = form.cleaned_data['texto_sentenca']
            arquivo_pdf = form.cleaned_data.get('arquivo_sentenca_pdf')

            if arquivo_pdf:
                try:
                    texto_sentenca = extract_text_from_pdf(arquivo_pdf)
                except RuntimeError as exc:
                    form.add_error('arquivo_sentenca_pdf', str(exc))
                    return render(request, 'calculadora/novo.html', {'form': form})

            calculo = CalculoCondenacaoCivel.objects.create(
                usuario=request.user,
                titulo=form.cleaned_data['titulo'],
                texto_sentenca=texto_sentenca,
                arquivo_sentenca_pdf=arquivo_pdf,
                status=CalculoCondenacaoCivel.STATUS_RASCUNHO,
            )

            extracao, metadata = extract_civil_parameters(calculo.texto_sentenca)
            calculo.parametros_extraidos = extracao
            calculo.provedor_extracao = metadata.provider
            calculo.modelo_extracao = metadata.model
            calculo.observacoes_extracao = metadata.warning
            calculo.status = (
                CalculoCondenacaoCivel.STATUS_EXTRAIDO
                if extracao.get('parametros')
                else CalculoCondenacaoCivel.STATUS_ERRO
            )
            if not calculo.titulo:
                calculo.titulo = (
                    extracao.get('resumo_condenacao', '')[:200]
                    or (arquivo_pdf.name.rsplit('.', 1)[0][:200] if arquivo_pdf else '')
                )
            calculo.save()

            if metadata.warning:
                messages.warning(
                    request,
                    f"Extracao concluida com fallback heuristico. Revise todos os parametros. Detalhe: {metadata.warning}",
                )
            else:
                if arquivo_pdf:
                    messages.success(request, "PDF processado com sucesso. Revise os parametros antes de calcular.")
                else:
                    messages.success(request, "Sentenca analisada. Revise os parametros antes de calcular.")
            return redirect('calculadora_detalhe', calculo_id=calculo.id)
    else:
        form = SentencaExtracaoForm()

    return render(request, 'calculadora/novo.html', {'form': form})


@login_required
def detalhe_calculo(request, calculo_id):
    calculo = _get_calculo_for_user(request.user, calculo_id)

    if request.method == 'POST':
        form = ParametrosCalculoForm(request.POST)
        if form.is_valid():
            resultado, memoria = calculate_civil_condemnation(form.cleaned_data)
            calculo.parametros_confirmados = {
                key: (
                    value.isoformat() if hasattr(value, 'isoformat') else (format(value, 'f') if hasattr(value, 'quantize') else value)
                )
                for key, value in form.cleaned_data.items()
            }
            calculo.resultado_calculo = resultado
            calculo.memoria_calculo = memoria
            calculo.status = CalculoCondenacaoCivel.STATUS_CALCULADO
            calculo.save()
            messages.success(request, "Calculo atualizado com sucesso.")
            return redirect('calculadora_detalhe', calculo_id=calculo.id)
    else:
        form = ParametrosCalculoForm(initial=calculation_form_initial(calculo))

    return render(
        request,
        'calculadora/detalhe.html',
        {
            'calculo': calculo,
            'form': form,
            'parametros_extraidos': calculo.parametros_extraidos.get('parametros', {}),
            'resumo_extracao': calculo.parametros_extraidos.get('resumo_condenacao', ''),
            'itens_reconhecidos': calculo.parametros_extraidos.get('itens_reconhecidos', []),
            'campos_pendentes': calculo.parametros_extraidos.get('campos_pendentes', []),
            'resultado': calculo.resultado_calculo,
        },
    )
