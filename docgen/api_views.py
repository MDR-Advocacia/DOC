from datetime import datetime

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from .models import DocumentoGerado, ExecucaoCapturaProcesso, ProcessoStatus, Template
from .permissions import HasWorkerToken
from .serializers import DocumentoSerializer, ExecucaoCapturaProcessoSerializer
from .processos_services import (
    claim_execucao_para_worker,
    concluir_execucao_com_arquivo,
    falhar_execucao,
    registrar_heartbeat_execucao,
)
from .utils import renderizar_template_docx


class BibliotecaAPIView(APIView):
    """
    GET: Lista apenas os documentos do usuario logado.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get(self, request):
        documentos = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')

        template_id = request.query_params.get('template_id')
        if template_id:
            documentos = documentos.filter(template_id=template_id)

        serializer = DocumentoSerializer(documentos, many=True)
        return Response(serializer.data)


class GerarDocumentoAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'doc_gen'

    @swagger_auto_schema(
        operation_description="Gera um documento Word. Limite: 20/minuto.",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['template_id', 'dados'],
            properties={
                'template_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                'dados': openapi.Schema(type=openapi.TYPE_OBJECT),
            },
        ),
        responses={201: "Criado", 400: "Erro", 404: "Nao encontrado", 429: "Muitas requisicoes"},
    )
    def post(self, request):
        template_id = request.data.get('template_id')
        dados = request.data.get('dados')

        if not template_id or not isinstance(dados, dict):
            return Response(
                {"erro": "Campos 'template_id' e 'dados' sao obrigatorios."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        template = get_object_or_404(Template, pk=template_id, ativo=True)

        try:
            conteudo_docx, dados_log, _ = renderizar_template_docx(template, dados=dados)
            nome_base = template.titulo.strip().replace(' ', '_') or "documento"
            nome_arquivo = f"{nome_base}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"

            documento = DocumentoGerado.objects.create(
                template=template,
                usuario=request.user,
                dados_inputados=dados_log,
            )
            documento.arquivo_final.save(nome_arquivo, ContentFile(conteudo_docx), save=True)

            return Response(
                {
                    "status": "sucesso",
                    "mensagem": "Documento gerado com sucesso.",
                    "id": documento.id,
                    "arquivo_url": documento.arquivo_final.url if documento.arquivo_final else None,
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as exc:  # pragma: no cover - error path
            return Response(
                {"erro": f"Erro interno: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class WorkerClaimAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasWorkerToken]
    parser_classes = [JSONParser]
    throttle_classes = []

    def post(self, request):
        worker_id = (request.data.get('worker_id') or 'processos-worker').strip()
        execucao = claim_execucao_para_worker(worker_id)
        if not execucao:
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = ExecucaoCapturaProcessoSerializer(execucao)
        return Response(serializer.data, status=status.HTTP_200_OK)


class WorkerHeartbeatAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasWorkerToken]
    parser_classes = [JSONParser]
    throttle_classes = []

    def post(self, request, execucao_id):
        execucao = get_object_or_404(ExecucaoCapturaProcesso, id=execucao_id)
        registrar_heartbeat_execucao(execucao, mensagem=request.data.get('mensagem', ''))
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class WorkerCompleteAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasWorkerToken]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = []

    def post(self, request, execucao_id):
        execucao = get_object_or_404(ExecucaoCapturaProcesso.objects.select_related('processo'), id=execucao_id)
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            return Response({'erro': "Envie o arquivo em 'arquivo'."}, status=status.HTTP_400_BAD_REQUEST)

        concluir_execucao_com_arquivo(
            execucao,
            arquivo_upload=arquivo,
            checksum=(request.data.get('checksum') or '').strip(),
            mensagem=(request.data.get('mensagem') or '').strip(),
            tribunal_url=(request.data.get('tribunal_url') or '').strip(),
        )
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class WorkerFailAPIView(APIView):
    authentication_classes = []
    permission_classes = [HasWorkerToken]
    parser_classes = [JSONParser]
    throttle_classes = []

    def post(self, request, execucao_id):
        execucao = get_object_or_404(ExecucaoCapturaProcesso.objects.select_related('processo'), id=execucao_id)
        status_final = (request.data.get('status') or '').strip()
        mensagem = (request.data.get('mensagem') or '').strip()
        if status_final not in {
            ProcessoStatus.PROCESSO_NAO_ENCONTRADO,
            ProcessoStatus.PETICAO_NAO_LOCALIZADA,
            ProcessoStatus.FALHA_TECNICA,
        }:
            return Response({'erro': 'Status de falha invalido.'}, status=status.HTTP_400_BAD_REQUEST)
        if not mensagem:
            return Response({'erro': 'Informe a mensagem da falha.'}, status=status.HTTP_400_BAD_REQUEST)

        falhar_execucao(
            execucao,
            status_final=status_final,
            mensagem=mensagem,
            tribunal_url=(request.data.get('tribunal_url') or '').strip(),
        )
        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
