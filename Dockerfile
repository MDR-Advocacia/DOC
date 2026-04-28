# Usa uma imagem leve do Python 3.13
FROM python:3.13-slim

# Evita que o Python grave arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Define onde o app vai ficar dentro do container
WORKDIR /app

# Instala dependências do sistema (necessárias para o Postgres e healthcheck)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
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
