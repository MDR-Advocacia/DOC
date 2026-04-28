import os
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import CalculoCondenacaoCivel
from .forms import SentencaExtracaoForm
from .services import calculate_civil_condemnation, extract_civil_parameters


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='doc-calculadora-tests-')


@override_settings(
    MEDIA_ROOT=TEST_MEDIA_ROOT,
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
)
@patch.dict(os.environ, {'CALCULO_LLM_API_KEY': ''}, clear=False)
class CalculadoraTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_heuristic_extraction_identifies_basic_parameters(self):
        text = (
            "Julgo procedente o pedido para condenar a re ao pagamento de R$ 12.500,00, "
            "com juros de 1% ao mes a contar de 10/01/2024, correcao monetaria pelo INPC "
            "e honorarios advocaticios de 15%."
        )

        payload, metadata = extract_civil_parameters(text)

        self.assertEqual(metadata.provider, 'heuristico')
        self.assertEqual(payload['parametros']['valor_principal'], '12500.00')
        self.assertEqual(payload['parametros']['juros_mensais_percentual'], '1.0000')
        self.assertEqual(payload['parametros']['indice_correcao'], 'INPC')
        self.assertEqual(payload['parametros']['honorarios_percentual'], '15.0000')

    def test_calculation_engine_returns_expected_total(self):
        resultado, memoria = calculate_civil_condemnation(
            {
                'valor_principal': Decimal('1000.00'),
                'correcao_percentual': Decimal('10.00'),
                'indice_correcao': 'INPC',
                'data_termo_inicial_correcao': None,
                'juros_mensais_percentual': Decimal('1.00'),
                'data_termo_inicial_juros': '2026-01-01',
                'data_base_calculo': '2026-03-02',
                'honorarios_percentual': Decimal('10.00'),
                'multa_percentual': Decimal('2.00'),
                'outros_acrescimos': Decimal('50.00'),
                'descontos': Decimal('20.00'),
                'observacoes_calculo': 'Teste',
            }
        )

        self.assertEqual(resultado['principal_corrigido'], '1100.00')
        self.assertEqual(resultado['subtotal'], '1152.00')
        self.assertEqual(resultado['valor_honorarios'], '115.20')
        self.assertEqual(resultado['valor_multa'], '23.04')
        self.assertEqual(resultado['total_geral'], '1290.24')
        self.assertIn('Observacoes: Teste', memoria)

    def test_authenticated_user_can_create_and_calculate_case(self):
        user = User.objects.create_user(username='calc@example.com', password='SenhaForte123!', is_active=True)
        self.client.force_login(user)

        response = self.client.post(
            reverse('calculadora_novo'),
            data={
                'titulo': 'Caso Maria',
                'texto_sentenca': 'Condeno ao pagamento de R$ 5.000,00 com honorarios de 10%.',
            },
        )

        calculo = CalculoCondenacaoCivel.objects.get(usuario=user)
        self.assertRedirects(response, reverse('calculadora_detalhe', args=[calculo.id]))
        self.assertEqual(calculo.status, CalculoCondenacaoCivel.STATUS_EXTRAIDO)

        response = self.client.post(
            reverse('calculadora_detalhe', args=[calculo.id]),
            data={
                'valor_principal': '5000,00',
                'correcao_percentual': '3,50',
                'indice_correcao': 'INPC',
                'data_termo_inicial_correcao': '',
                'juros_mensais_percentual': '1,00',
                'data_termo_inicial_juros': '2026-01-01',
                'data_base_calculo': '2026-02-01',
                'honorarios_percentual': '10,00',
                'multa_percentual': '0,00',
                'outros_acrescimos': '0,00',
                'descontos': '0,00',
                'observacoes_calculo': 'Revisado manualmente',
            },
        )

        self.assertRedirects(response, reverse('calculadora_detalhe', args=[calculo.id]))
        calculo.refresh_from_db()
        self.assertEqual(calculo.status, CalculoCondenacaoCivel.STATUS_CALCULADO)
        self.assertEqual(calculo.resultado_calculo['total_geral'], '5751.32')

    def test_extraction_form_requires_text_or_pdf(self):
        form = SentencaExtracaoForm(data={'titulo': 'Caso sem conteudo', 'texto_sentenca': ''})

        self.assertFalse(form.is_valid())
        self.assertIn('Informe o texto da sentenca ou envie um PDF para extracao.', form.non_field_errors())

    @patch('calculadora.views.extract_text_from_pdf')
    def test_authenticated_user_can_create_case_from_pdf(self, extract_text_from_pdf_mock):
        extract_text_from_pdf_mock.return_value = (
            'Condeno a re ao pagamento de R$ 8.900,00 com juros de 1% ao mes e honorarios de 12%.'
        )
        user = User.objects.create_user(username='pdf@example.com', password='SenhaForte123!', is_active=True)
        self.client.force_login(user)

        uploaded_file = SimpleUploadedFile(
            'sentenca.pdf',
            b'%PDF-1.4 fake pdf for mocked extraction',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('calculadora_novo'),
            data={
                'titulo': '',
                'texto_sentenca': '',
                'arquivo_sentenca_pdf': uploaded_file,
            },
        )

        calculo = CalculoCondenacaoCivel.objects.get(usuario=user)
        self.assertRedirects(response, reverse('calculadora_detalhe', args=[calculo.id]))
        self.assertTrue(calculo.arquivo_sentenca_pdf.name.endswith('.pdf'))
        self.assertEqual(calculo.texto_sentenca, extract_text_from_pdf_mock.return_value)
        self.assertEqual(calculo.parametros_extraidos['parametros']['valor_principal'], '8900.00')
