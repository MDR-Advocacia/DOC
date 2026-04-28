import json
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from docx import Document

from .models import (
    ArquivoArmazenado,
    ArquivoProcesso,
    DocumentoGerado,
    Equipe,
    ExecucaoCapturaProcesso,
    LoteImportacaoProcessos,
    PastaPersonalizada,
    Processo,
    ProcessoStatus,
    Setor,
    Template,
    TemplateFavorito,
)
from .processos_constants import TRIBUNAIS_ESTADUAIS
from .processos_services import concluir_execucao_com_arquivo, resolver_tribunal_por_cnj
from .processos_worker.adapters import (
    CapturedDocument,
    GenericWhomTribunalAdapter,
    ProcessNotFound,
    TribunalAutomationConfig,
    load_tribunal_configs,
    resolve_extension_id,
)
from .processos_worker.runner import ProcessosWorker


TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="docgen-test-media-"))
TEST_STATIC_ROOT = TEST_MEDIA_ROOT / "staticfiles"
TEST_STATIC_ROOT.mkdir(parents=True, exist_ok=True)
PROCESSOS_TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="docgen-processos-test-media-"))
PROCESSOS_TEST_STATIC_ROOT = PROCESSOS_TEST_MEDIA_ROOT / "staticfiles"
PROCESSOS_TEST_STATIC_ROOT.mkdir(parents=True, exist_ok=True)


def _docx_upload(nome_arquivo, conteudo):
    documento = Document()
    documento.add_paragraph(conteudo)
    buffer = BytesIO()
    documento.save(buffer)
    buffer.seek(0)
    return SimpleUploadedFile(
        nome_arquivo,
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )


def _csv_upload(nome_arquivo, conteudo):
    return SimpleUploadedFile(
        nome_arquivo,
        conteudo.encode('utf-8'),
        content_type='text/csv',
    )


def _pdf_upload(nome_arquivo):
    return SimpleUploadedFile(
        nome_arquivo,
        b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF',
        content_type='application/pdf',
    )


def _numero_cnj_para_tribunal(tribunal_codigo, sequencial='0000001', ano='2026', origem='0001'):
    tribunal_numero = tribunal_codigo.split('.')[-1]
    base = f"{sequencial}{ano}8{tribunal_numero}{origem}"
    digito_verificador = 98 - (int(base + '00') % 97)
    return f"{sequencial}-{digito_verificador:02d}.{ano}.8.{tribunal_numero}.{origem}"


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STATIC_ROOT=TEST_STATIC_ROOT)
class DocgenFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.setor = Setor.objects.create(nome='Civel')
        self.template = Template.objects.create(
            titulo='Peticao Inicial',
            descricao='Modelo base',
            setor=self.setor,
            arquivo_template=_docx_upload('peticao.docx', 'Ola {{ cliente }}'),
            configuracao_campos=[
                {
                    'tag': 'cliente',
                    'label': 'Cliente',
                    'tipo': 'text',
                    'dependencia': '',
                    'opcoes': '',
                }
            ],
            ativo=True,
        )

    def test_api_gera_documento_e_salva_arquivo(self):
        usuario = User.objects.create_user(username='api@example.com', password='SenhaForte123!', is_active=True)
        self.client.force_login(usuario)

        response = self.client.post(
            reverse('api_gerar'),
            data=json.dumps({'template_id': self.template.id, 'dados': {'cliente': 'Maria'}}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        documento = DocumentoGerado.objects.get(usuario=usuario)
        self.assertTrue(documento.arquivo_final.name.endswith('.docx'))

    def test_pasta_compartilhada_exibe_favorito_para_membro_da_equipe(self):
        dono = User.objects.create_user(username='dono@example.com', password='SenhaForte123!', is_active=True)
        membro = User.objects.create_user(username='membro@example.com', password='SenhaForte123!', is_active=True)

        equipe = Equipe.objects.create(nome='Equipe Civel')
        equipe.supervisores.add(dono)
        equipe.membros.add(membro)

        pasta = PastaPersonalizada.objects.create(usuario=dono, nome='Compartilhados', compartilhada=True)
        pasta.equipes_permitidas.add(equipe)

        TemplateFavorito.objects.create(usuario=dono, template=self.template, pasta=pasta)

        self.client.force_login(membro)
        response = self.client.get(reverse('minha_biblioteca'), {'pasta': pasta.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Peticao Inicial')
        self.assertContains(response, 'dono@example.com')

    def test_parar_compartilhamento_remove_visibilidade_para_membro(self):
        dono = User.objects.create_user(username='gestor@example.com', password='SenhaForte123!', is_active=True)
        membro = User.objects.create_user(username='time@example.com', password='SenhaForte123!', is_active=True)

        equipe = Equipe.objects.create(nome='Equipe Trabalhista')
        equipe.supervisores.add(dono)
        equipe.membros.add(membro)

        pasta = PastaPersonalizada.objects.create(usuario=dono, nome='Pasta da Equipe', compartilhada=True)
        pasta.equipes_permitidas.add(equipe)
        TemplateFavorito.objects.create(usuario=dono, template=self.template, pasta=pasta)

        self.client.force_login(dono)
        response = self.client.post(reverse('parar_compartilhamento', args=[pasta.id]))

        self.assertRedirects(response, reverse('minha_biblioteca'))
        pasta.refresh_from_db()
        self.assertFalse(pasta.compartilhada)

        self.client.force_login(membro)
        biblioteca = self.client.get(reverse('minha_biblioteca'))
        self.assertNotContains(biblioteca, 'Pasta da Equipe')
        self.assertNotContains(biblioteca, 'Peticao Inicial')

    def test_pasta_restrita_da_biblioteca_respeita_usuarios_escolhidos(self):
        admin = User.objects.create_user(username='admin-lib@example.com', password='SenhaForte123!', is_active=True, is_staff=True)
        permitido = User.objects.create_user(username='permitido-lib@example.com', password='SenhaForte123!', is_active=True)
        bloqueado = User.objects.create_user(username='bloqueado-lib@example.com', password='SenhaForte123!', is_active=True)

        pasta = PastaPersonalizada.objects.create(
            usuario=admin,
            nome='Modelos Restritos',
            escopo=PastaPersonalizada.ESCOPO_BIBLIOTECA,
            nivel_acesso=PastaPersonalizada.ACESSO_RESTRITO,
            compartilhada=True,
        )
        pasta.usuarios_permitidos.add(permitido)
        TemplateFavorito.objects.create(usuario=admin, template=self.template, pasta=pasta)

        self.client.force_login(permitido)
        response_permitido = self.client.get(reverse('minha_biblioteca'), {'pasta': pasta.id})
        self.assertEqual(response_permitido.status_code, 200)
        self.assertContains(response_permitido, 'Peticao Inicial')

        self.client.force_login(bloqueado)
        response_bloqueado = self.client.get(reverse('minha_biblioteca'), {'pasta': pasta.id})
        self.assertEqual(response_bloqueado.status_code, 404)

    def test_membro_nao_move_favorito_para_pasta_compartilhada_sem_edicao(self):
        dono = User.objects.create_user(username='dono-move@example.com', password='SenhaForte123!', is_active=True)
        membro = User.objects.create_user(username='membro-move@example.com', password='SenhaForte123!', is_active=True)
        equipe = Equipe.objects.create(nome='Equipe Move')
        equipe.supervisores.add(dono)
        equipe.membros.add(membro)

        pasta = PastaPersonalizada.objects.create(
            usuario=dono,
            nome='Somente leitura',
            compartilhada=True,
            nivel_acesso=PastaPersonalizada.ACESSO_EQUIPES,
        )
        pasta.equipes_permitidas.add(equipe)
        favorito = TemplateFavorito.objects.create(usuario=membro, template=self.template)

        self.client.force_login(membro)
        response = self.client.post(
            reverse('mover_para_pasta', args=[self.template.id]),
            data=json.dumps({'pasta_id': pasta.id}),
            content_type='application/json',
        )

        favorito.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(favorito.pasta)

    def test_repositorio_com_pasta_restrita_por_usuario(self):
        admin = User.objects.create_user(username='admin-arq@example.com', password='SenhaForte123!', is_active=True, is_staff=True)
        permitido = User.objects.create_user(username='permitido-arq@example.com', password='SenhaForte123!', is_active=True)
        bloqueado = User.objects.create_user(username='bloqueado-arq@example.com', password='SenhaForte123!', is_active=True)

        self.client.force_login(admin)
        response_criar = self.client.post(
            reverse('criar_pasta_arquivo'),
            {
                'nome': 'Arquivos Restritos',
                'nivel_acesso': PastaPersonalizada.ACESSO_RESTRITO,
                'usuarios': [permitido.id],
            },
        )
        self.assertRedirects(response_criar, reverse('arquivos_lista'))
        pasta = PastaPersonalizada.objects.get(nome='Arquivos Restritos')
        self.assertEqual(pasta.escopo, PastaPersonalizada.ESCOPO_REPOSITORIO)
        self.assertEqual(pasta.nivel_acesso, PastaPersonalizada.ACESSO_RESTRITO)
        self.assertTrue(pasta.usuarios_permitidos.filter(id=permitido.id).exists())

        arquivo = ArquivoArmazenado.objects.create(
            arquivo=_pdf_upload('segredo.pdf'),
            nome_original='segredo.pdf',
            tipo=ArquivoArmazenado.TIPO_PDF,
            usuario=admin,
            pasta=pasta,
            tamanho_bytes=128,
        )

        self.client.force_login(permitido)
        lista_permitido = self.client.get(reverse('arquivos_lista'), {'pasta': pasta.id})
        download_permitido = self.client.get(reverse('arquivo_download', args=[arquivo.id]))
        self.assertContains(lista_permitido, 'segredo.pdf')
        self.assertEqual(download_permitido.status_code, 200)

        self.client.force_login(bloqueado)
        lista_bloqueado = self.client.get(reverse('arquivos_lista'))
        download_bloqueado = self.client.get(reverse('arquivo_download', args=[arquivo.id]))
        self.assertNotContains(lista_bloqueado, 'segredo.pdf')
        self.assertEqual(download_bloqueado.status_code, 404)

    def test_supervisor_nao_staff_consegue_gerenciar_sua_equipe(self):
        supervisor = User.objects.create_user(username='supervisor@example.com', password='SenhaForte123!', is_active=True)
        equipe = Equipe.objects.create(nome='Equipe Supervisor')
        equipe.supervisores.add(supervisor)

        self.client.force_login(supervisor)

        resposta_equipes = self.client.get(reverse('gerenciar_equipes'))
        resposta_membros = self.client.get(reverse('gerenciar_membros_equipe', args=[equipe.id]))

        self.assertEqual(resposta_equipes.status_code, 200)
        self.assertEqual(resposta_membros.status_code, 200)
        self.assertContains(resposta_equipes, 'Equipe Supervisor')

    def test_usuario_sem_supervisao_recebe_forbidden_na_gestao(self):
        usuario = User.objects.create_user(username='usuario@example.com', password='SenhaForte123!', is_active=True)
        self.client.force_login(usuario)

        response = self.client.get(reverse('gerenciar_equipes'))
        self.assertEqual(response.status_code, 403)

    def test_usuario_comum_nao_acessa_disparo_obrigacao_fazer(self):
        usuario = User.objects.create_user(username='comum@example.com', password='SenhaForte123!', is_active=True)
        self.client.force_login(usuario)

        response = self.client.get(reverse('disparar_obrigacao_fazer'))
        self.assertEqual(response.status_code, 403)

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='doc@example.com',
    )
    def test_admin_dispara_emails_individuais_com_roteamento_automatico_e_pdf_por_pedido(self):
        admin = User.objects.create_user(
            username='admin@example.com',
            password='SenhaForte123!',
            is_active=True,
            is_staff=True,
        )
        self.client.force_login(admin)

        planilha = _csv_upload(
            'pedidos.csv',
            (
                'cliente,tipo_demanda,carteira,pedido,cpf,resultado_sentenca,data_sentenca,id_oficio,comarca,anexo_pdf,numero_processo\n'
                'Maria,suspensao_liquidacao_reativacao,master,Apresentar documentos,12345678901,Procedente,10/04/2026,OF-123,Salvador,maria.pdf,0001234-56.2026.8.26.0001\n'
                'Joao,suspensao_liquidacao_reativacao,pkl_credecesta,Regularizar cadastro,10987654321,Parcialmente procedente,15/04/2026,OF-987,Fortaleza,joao.pdf,0009876-12.2026.8.26.0001\n'
            ),
        )
        anexos = [
            _pdf_upload('maria.pdf'),
            _pdf_upload('joao.pdf'),
        ]

        response = self.client.post(
            reverse('disparar_obrigacao_fazer'),
            {
                'planilha': planilha,
                'anexos_pdf': anexos,
                'confirmar_envio': 'on',
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('disparar_obrigacao_fazer'))
        self.assertContains(response, '2 email(s) enviados com sucesso.')
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ['suspensaoeliquidacaobko@bancomaster.com.br'])
        self.assertEqual(mail.outbox[1].to, ['desaverbacao@grupoterrafirme.com.br'])
        self.assertIn('Resultado da sentenca: Procedente', mail.outbox[0].body)
        self.assertIn('ID do oficio: OF-123', mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].attachments[0][0], 'maria.pdf')
        self.assertEqual(mail.outbox[1].attachments[0][0], 'joao.pdf')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='doc@example.com',
    )
    def test_admin_recebe_erro_quando_pdf_da_planilha_nao_foi_enviado(self):
        admin = User.objects.create_user(
            username='admin2@example.com',
            password='SenhaForte123!',
            is_active=True,
            is_staff=True,
        )
        self.client.force_login(admin)

        planilha = _csv_upload(
            'pedidos.csv',
            (
                'cliente,tipo_demanda,carteira,pedido,cpf,resultado_sentenca,data_sentenca,id_oficio,comarca,anexo_pdf\n'
                'Maria,suspensao_liquidacao_reativacao,master,Apresentar documentos,12345678901,Procedente,10/04/2026,OF-123,Salvador,maria.pdf\n'
            ),
        )

        response = self.client.post(
            reverse('disparar_obrigacao_fazer'),
            {
                'planilha': planilha,
                'anexos_pdf': [_pdf_upload('outro.pdf')],
                'confirmar_envio': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "o PDF &#x27;maria.pdf&#x27; nao foi enviado.")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(
    MEDIA_ROOT=PROCESSOS_TEST_MEDIA_ROOT,
    STATIC_ROOT=PROCESSOS_TEST_STATIC_ROOT,
    PROCESSOS_WORKER_TOKEN='worker-test-token',
)
class ProcessosFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PROCESSOS_TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin-processos@example.com',
            email='admin-processos@example.com',
            password='SenhaForte123!',
            is_active=True,
            is_staff=True,
        )
        self.usuario = User.objects.create_user(
            username='usuario-processos@example.com',
            email='usuario-processos@example.com',
            password='SenhaForte123!',
            is_active=True,
        )
        self.outro_usuario = User.objects.create_user(
            username='outro-processos@example.com',
            email='outro-processos@example.com',
            password='SenhaForte123!',
            is_active=True,
        )

    def _headers_worker(self):
        return {'HTTP_AUTHORIZATION': 'Bearer worker-test-token'}

    def test_importacao_de_lote_cria_processo_e_execucao(self):
        self.client.force_login(self.admin)
        numero_cnj = _numero_cnj_para_tribunal('8.25')

        response = self.client.post(
            reverse('processos_importar_lote'),
            {
                'planilha': _csv_upload(
                    'processos.csv',
                    (
                        'numero_processo,usuario_email,observacao,referencia_interna\n'
                        f'{numero_cnj},{self.usuario.username},Cliente prioritario,REF-001\n'
                    ),
                ),
                'confirmar_importacao': 'on',
            },
            follow=True,
        )

        self.assertRedirects(response, reverse('processos_monitoramento'))
        processo = Processo.objects.get(usuario=self.usuario, numero_cnj=numero_cnj)
        self.assertEqual(processo.tribunal_codigo, '8.25')
        self.assertEqual(processo.status_atual, ProcessoStatus.EM_FILA)
        self.assertEqual(processo.referencia_interna, 'REF-001')
        self.assertTrue(LoteImportacaoProcessos.objects.exists())
        self.assertEqual(ExecucaoCapturaProcesso.objects.filter(processo=processo).count(), 1)

    def test_importacao_rejeita_cnj_invalido(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('processos_importar_lote'),
            {
                'planilha': _csv_upload(
                    'processos-invalidos.csv',
                    (
                        'numero_processo,usuario_email\n'
                        f'0000001-00.2026.8.25.0001,{self.usuario.username}\n'
                    ),
                ),
                'confirmar_importacao': 'on',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'nao passou na validacao do CNJ')
        self.assertEqual(Processo.objects.count(), 0)

    def test_usuario_comum_nao_acessa_monitoramento(self):
        self.client.force_login(self.usuario)
        response = self.client.get(reverse('processos_monitoramento'))
        self.assertEqual(response.status_code, 403)

    def test_usuario_visualiza_apenas_processos_proprios(self):
        processo_usuario = Processo.objects.create(
            usuario=self.usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.06', sequencial='0000002'),
            tribunal_codigo='8.06',
            tribunal_nome='Ceara',
            status_atual=ProcessoStatus.EM_FILA,
        )
        processo_outro = Processo.objects.create(
            usuario=self.outro_usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.19', sequencial='0000003'),
            tribunal_codigo='8.19',
            tribunal_nome='Rio de Janeiro',
            status_atual=ProcessoStatus.EM_FILA,
        )

        self.client.force_login(self.usuario)
        response = self.client.get(reverse('processos_lista'))

        self.assertContains(response, processo_usuario.numero_cnj)
        self.assertNotContains(response, processo_outro.numero_cnj)

    def test_download_e_detalhe_respeitam_permissao(self):
        processo = Processo.objects.create(
            usuario=self.usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.10', sequencial='0000004'),
            tribunal_codigo='8.10',
            tribunal_nome='Maranhao',
            status_atual=ProcessoStatus.PROCESSANDO,
        )
        execucao = ExecucaoCapturaProcesso.objects.create(
            processo=processo,
            status=ProcessoStatus.PROCESSANDO,
            tentativa=1,
        )
        arquivo = concluir_execucao_com_arquivo(execucao, _pdf_upload('inicial.pdf'))

        self.client.force_login(self.outro_usuario)
        detalhe = self.client.get(reverse('processo_detalhe', args=[processo.id]))
        download = self.client.get(reverse('download_arquivo_processo', args=[arquivo.id]))

        self.assertEqual(detalhe.status_code, 404)
        self.assertEqual(download.status_code, 403)

        self.client.force_login(self.usuario)
        detalhe_ok = self.client.get(reverse('processo_detalhe', args=[processo.id]))
        download_ok = self.client.get(reverse('download_arquivo_processo', args=[arquivo.id]))

        self.assertEqual(detalhe_ok.status_code, 200)
        self.assertEqual(download_ok.status_code, 200)

    def test_worker_claim_nao_duplica_execucao(self):
        processo = Processo.objects.create(
            usuario=self.usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.17', sequencial='0000005'),
            tribunal_codigo='8.17',
            tribunal_nome='Pernambuco',
            status_atual=ProcessoStatus.EM_FILA,
        )
        execucao = ExecucaoCapturaProcesso.objects.create(
            processo=processo,
            status=ProcessoStatus.EM_FILA,
        )

        primeira = self.client.post(
            reverse('api_processos_worker_claim'),
            data=json.dumps({'worker_id': 'worker-a'}),
            content_type='application/json',
            **self._headers_worker(),
        )
        segunda = self.client.post(
            reverse('api_processos_worker_claim'),
            data=json.dumps({'worker_id': 'worker-b'}),
            content_type='application/json',
            **self._headers_worker(),
        )

        execucao.refresh_from_db()
        self.assertEqual(primeira.status_code, 200)
        self.assertEqual(segunda.status_code, 204)
        self.assertEqual(execucao.status, ProcessoStatus.PROCESSANDO)
        self.assertEqual(execucao.worker_id, 'worker-a')
        self.assertEqual(execucao.tentativa, 1)

    def test_worker_claim_nao_sofre_throttle_no_polling(self):
        for _ in range(12):
            response = self.client.post(
                reverse('api_processos_worker_claim'),
                data=json.dumps({'worker_id': 'worker-poll'}),
                content_type='application/json',
                **self._headers_worker(),
            )
            self.assertEqual(response.status_code, 204)

    def test_worker_complete_substitui_arquivo_atual(self):
        processo = Processo.objects.create(
            usuario=self.usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.21', sequencial='0000006'),
            tribunal_codigo='8.21',
            tribunal_nome='Rio Grande do Sul',
            status_atual=ProcessoStatus.PROCESSANDO,
        )
        execucao_antiga = ExecucaoCapturaProcesso.objects.create(
            processo=processo,
            status=ProcessoStatus.PROCESSANDO,
            tentativa=1,
        )
        arquivo_antigo = concluir_execucao_com_arquivo(execucao_antiga, _pdf_upload('antigo.pdf'))
        nova_execucao = ExecucaoCapturaProcesso.objects.create(
            processo=processo,
            status=ProcessoStatus.PROCESSANDO,
            tentativa=2,
        )

        response = self.client.post(
            reverse('api_processos_worker_complete', args=[nova_execucao.id]),
            data={
                'arquivo': _pdf_upload('novo.pdf'),
                'checksum': 'checksum-novo',
                'mensagem': 'Documento atualizado.',
            },
            **self._headers_worker(),
        )

        arquivo_antigo.refresh_from_db()
        novo_arquivo = ArquivoProcesso.objects.filter(processo=processo, atual=True).get()
        processo.refresh_from_db()
        nova_execucao.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(arquivo_antigo.atual)
        self.assertEqual(novo_arquivo.checksum, 'checksum-novo')
        self.assertEqual(processo.status_atual, ProcessoStatus.BAIXADO)
        self.assertEqual(nova_execucao.status, ProcessoStatus.BAIXADO)

    def test_worker_fail_registra_falha(self):
        processo = Processo.objects.create(
            usuario=self.usuario,
            numero_cnj=_numero_cnj_para_tribunal('8.24', sequencial='0000007'),
            tribunal_codigo='8.24',
            tribunal_nome='Santa Catarina',
            status_atual=ProcessoStatus.PROCESSANDO,
        )
        execucao = ExecucaoCapturaProcesso.objects.create(
            processo=processo,
            status=ProcessoStatus.PROCESSANDO,
            tentativa=1,
        )

        response = self.client.post(
            reverse('api_processos_worker_fail', args=[execucao.id]),
            data=json.dumps(
                {
                    'status': ProcessoStatus.PETICAO_NAO_LOCALIZADA,
                    'mensagem': 'Documento inicial nao apareceu na lista.',
                }
            ),
            content_type='application/json',
            **self._headers_worker(),
        )

        execucao.refresh_from_db()
        processo.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(execucao.status, ProcessoStatus.PETICAO_NAO_LOCALIZADA)
        self.assertEqual(processo.status_atual, ProcessoStatus.PETICAO_NAO_LOCALIZADA)

    def test_mapeamento_cobre_todos_os_27_tjs(self):
        for indice, (codigo, nome) in enumerate(TRIBUNAIS_ESTADUAIS.items(), start=10):
            numero_cnj = _numero_cnj_para_tribunal(codigo, sequencial=f'{indice:07d}')
            codigo_resolvido, nome_resolvido = resolver_tribunal_por_cnj(numero_cnj)
            self.assertEqual(codigo_resolvido, codigo)
            self.assertEqual(nome_resolvido, nome)

    def test_smoke_worker_separado(self):
        repo_root = Path(__file__).resolve().parent.parent
        docker_compose = (repo_root / 'docker-compose.yml').read_text(encoding='utf-8')

        self.assertTrue((repo_root / 'Dockerfile.processos-worker').exists())
        self.assertTrue((repo_root / 'requirements.processos-worker.txt').exists())
        self.assertIn('processos-worker:', docker_compose)
        self.assertIn('processos_worker_profile', docker_compose)

        with patch.dict(
            os.environ,
            {
                'PROCESSOS_WORKER_TOKEN': 'worker-test-token',
                'PROCESSOS_WORKER_API_BASE_URL': 'http://web:8000',
                'PROCESSOS_WORKER_BROWSER_PROFILE': str(repo_root / '.tmp-processos-profile'),
            },
            clear=False,
        ):
            worker = ProcessosWorker.from_env()
        self.assertEqual(worker.worker_id, 'processos-worker')

    def test_adapter_aceita_fluxo_via_whom_sem_url_manual(self):
        config = TribunalAutomationConfig(
            tribunal_codigo='8.05',
            tribunal_nome='Bahia',
            portal_url='',
            whom_system_name='TJBA Pje - 1º grau',
            search_input_selector='#numeroProcesso',
            search_submit_selector='',
            document_row_selector='.documento',
            document_name_selector='.nome',
            document_download_selector='.download',
            process_not_found_text='',
            download_timeout_ms=1000,
            navigation_timeout_ms=1000,
        )

        adapter = GenericWhomTribunalAdapter(config)
        adapter._validate_configuration(config)

    def test_resolve_extension_id_le_configs_json(self):
        extension_dir = PROCESSOS_TEST_MEDIA_ROOT / 'fake-extension'
        extension_dir.mkdir(parents=True, exist_ok=True)
        (extension_dir / 'configs.json').write_text(
            json.dumps({'id': 'lnidijeaekolpfeckelhkomndglcglhh'}),
            encoding='utf-8',
        )

        self.assertEqual(
            resolve_extension_id(extension_dir),
            'lnidijeaekolpfeckelhkomndglcglhh',
        )

    def test_carrega_configuracoes_alternativas_do_mesmo_tribunal(self):
        with patch.dict(
            os.environ,
            {
                'PROCESSOS_TRIBUNAL_8_05_WHOM_SYSTEM': 'TJBA Pje - 1º grau',
                'PROCESSOS_TRIBUNAL_8_05_SEARCH_INPUT': '#pje',
                'PROCESSOS_TRIBUNAL_8_05_DOCUMENT_ROW': '.pje-row',
                'PROCESSOS_TRIBUNAL_8_05_ALT_1_WHOM_SYSTEM': 'TJBA Projudi - 1º Grau',
                'PROCESSOS_TRIBUNAL_8_05_ALT_1_SEARCH_INPUT': '#projudi',
                'PROCESSOS_TRIBUNAL_8_05_ALT_1_DOCUMENT_ROW': '.projudi-row',
            },
            clear=False,
        ):
            configs = load_tribunal_configs('8.05', 'Bahia')

        self.assertEqual(len(configs), 2)
        self.assertEqual(configs[0].whom_system_name, 'TJBA Pje - 1º grau')
        self.assertEqual(configs[0].source_label, 'principal')
        self.assertEqual(configs[1].whom_system_name, 'TJBA Projudi - 1º Grau')
        self.assertEqual(configs[1].source_label, 'alternativo 1')

    def test_adapter_tenta_sistema_alternativo_quando_primeiro_nao_encontra_processo(self):
        adapter = GenericWhomTribunalAdapter(
            [
                TribunalAutomationConfig(
                    tribunal_codigo='8.05',
                    tribunal_nome='Bahia',
                    portal_url='',
                    whom_system_name='TJBA Pje - 1º grau',
                    search_input_selector='#pje',
                    search_submit_selector='',
                    document_row_selector='.pje-row',
                    document_name_selector='.nome',
                    document_download_selector='.download',
                    process_not_found_text='',
                    download_timeout_ms=1000,
                    navigation_timeout_ms=1000,
                    source_label='principal',
                ),
                TribunalAutomationConfig(
                    tribunal_codigo='8.05',
                    tribunal_nome='Bahia',
                    portal_url='',
                    whom_system_name='TJBA Projudi - 1º Grau',
                    search_input_selector='#projudi',
                    search_submit_selector='',
                    document_row_selector='.projudi-row',
                    document_name_selector='.nome',
                    document_download_selector='.download',
                    process_not_found_text='',
                    download_timeout_ms=1000,
                    navigation_timeout_ms=1000,
                    source_label='alternativo 1',
                ),
            ]
        )
        captured = CapturedDocument(
            file_path=PROCESSOS_TEST_MEDIA_ROOT / 'arquivo.pdf',
            tribunal_url='https://exemplo.local/processo',
            document_name='Peticao Inicial',
        )

        with patch.object(
            GenericWhomTribunalAdapter,
            '_capture_with_config',
            side_effect=[
                ProcessNotFound('Processo nao encontrado no PJe.'),
                captured,
            ],
        ) as mocked_capture:
            result = adapter.capture_initial_petition(
                numero_cnj='8041588-22.2026.8.05.0001',
                browser_profile_dir=PROCESSOS_TEST_MEDIA_ROOT / 'profile',
                download_dir=PROCESSOS_TEST_MEDIA_ROOT / 'downloads',
            )

        self.assertEqual(result, captured)
        self.assertEqual(mocked_capture.call_count, 2)
