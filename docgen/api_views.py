from datetime import datetime

from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from .models import DocumentoGerado, Template
from .serializers import DocumentoSerializer
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
