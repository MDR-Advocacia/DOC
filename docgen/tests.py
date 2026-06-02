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
    DocumentoGerado,
    Equipe,
    PastaPersonalizada,
    Setor,
    Template,
    TemplateFavorito,
)


TEST_MEDIA_ROOT = Path(tempfile.mkdtemp(prefix="docgen-test-media-"))
TEST_STATIC_ROOT = TEST_MEDIA_ROOT / "staticfiles"
TEST_STATIC_ROOT.mkdir(parents=True, exist_ok=True)


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

        pasta = PastaPersonalizada.objects.create(
            usuario=dono,
            nome='Compartilhados',
            nivel_acesso=PastaPersonalizada.ACESSO_EQUIPES,
        )
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

        pasta = PastaPersonalizada.objects.create(
            usuario=dono,
            nome='Pasta da Equipe',
            nivel_acesso=PastaPersonalizada.ACESSO_EQUIPES,
        )
        pasta.equipes_permitidas.add(equipe)
        TemplateFavorito.objects.create(usuario=dono, template=self.template, pasta=pasta)

        self.client.force_login(dono)
        response = self.client.post(reverse('parar_compartilhamento', args=[pasta.id]))

        self.assertRedirects(response, reverse('minha_biblioteca'))
        pasta.refresh_from_db()
        self.assertEqual(pasta.nivel_acesso, PastaPersonalizada.ACESSO_PRIVADO)

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

