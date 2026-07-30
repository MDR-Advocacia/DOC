# Usa uma imagem leve do Python 3.13
FROM python:3.13-slim

# Evita que o Python grave arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define onde o app vai ficar dentro do container
WORKDIR /app

# Instala dependências do sistema (Postgres, healthcheck e pré-visualização).
#
# libreoffice-writer converte o .docx em PDF para a prévia fiel na tela — o
# navegador não renderiza .docx. Pesa a imagem em ~500MB; é o preço de mostrar
# a peça com a paginação e as margens reais.
#
# As fontes são o que faz a prévia bater com o Word. Sem elas o LibreOffice
# substitui por qualquer coisa e a quebra de linha muda:
#   fonts-liberation        → métrica de Arial, Times New Roman e Courier New
#   fonts-urw-base35        → URW Palladio, métrica de Palatino Linotype
#   fonts-crosextra-carlito → métrica de Calibri
#   fonts-crosextra-caladea → métrica de Cambria
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    libreoffice-writer \
    fonts-liberation \
    fonts-urw-base35 \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências do Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do projeto para dentro do container
COPY . /app/

# Cria pastas para arquivos estáticos e media; garante entrypoint executável
RUN mkdir -p /app/staticfiles /app/media \
    && chmod +x /app/scripts/entrypoint.sh

# Expõe a porta 8000
EXPOSE 8000

# Healthcheck — Coolify/Docker reciclam o container se /healthz/ não responder
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz/ || exit 1

# Comando: migrate + collectstatic + gunicorn (via entrypoint.sh)
CMD ["/app/scripts/entrypoint.sh"]
