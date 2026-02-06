# docgen/api_views.py
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.throttling import UserRateThrottle, ScopedRateThrottle
from django.shortcuts import get_object_or_404

from .models import Template, DocumentoGerado
from .serializers import DocumentoSerializer
from .permissions import IsDonoDoDocumento # <--- Importe a permissão nova

class BibliotecaAPIView(APIView):
    """
    GET: Lista APENAS os documentos do usuário logado.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle] # Aplica o limite de 100/min

    def get(self, request):
        # SEGURANÇA: Filtra .filter(usuario=request.user)
        # Ninguém vê documento de ninguém, a menos que você tire esse filtro.
        docs = DocumentoGerado.objects.filter(usuario=request.user).order_by('-data_geracao')
        
        template_id = request.query_params.get('template_id')
        if template_id:
            docs = docs.filter(template_id=template_id)
            
        serializer = DocumentoSerializer(docs, many=True)
        return Response(serializer.data)

class GerarDocumentoAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    # Define um escopo específico de limite (mais restrito pois gera carga na CPU)
    throttle_classes = [ScopedRateThrottle] 
    throttle_scope = 'doc_gen' # Usa a regra '20/minute' do settings.py

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
        responses={201: "Criado", 400: "Erro", 429: "Muitas requisições"}
    )
    def post(self, request):
        template_id = request.data.get('template_id')
        dados = request.data.get('dados')

        if not template_id or not dados:
            return Response(
                {"erro": "Campos 'template_id' e 'dados' são obrigatórios."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validação extra: O template existe?
        try:
            template = Template.objects.get(pk=template_id)
        except Template.DoesNotExist:
            return Response({"erro": "Template não encontrado"}, status=status.HTTP_404_NOT_FOUND)

        try:
            # 1. Simulação da Geração (Aqui entraria o docxtpl)
            # ... processamento ...
            
            # 2. Salva no banco vinculado ao usuário que pediu
            novo_doc = DocumentoGerado.objects.create(
                template=template,
                usuario=request.user, # <--- Vínculo de segurança
                dados_inputados=dados,
                # arquivo_final='...'
            )

            return Response({
                "status": "sucesso",
                "mensagem": "Documento gerado",
                "id": novo_doc.id,
                "limite_restante": "Verifique os headers da resposta"
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"erro": f"Erro interno: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )