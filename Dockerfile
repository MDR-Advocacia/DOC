# Usa uma imagem leve do Python 3.13
FROM python:3.13-slim

# Evita que o Python grave arquivos .pyc e permite logs em tempo real
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Define onde o app vai ficar dentro do container
WORKDIR /app

# Instala dependências do sistema (necessárias para o Postgres e outros)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependências do Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do projeto para dentro do container
COPY . /app/

# Cria pastas para arquivos estáticos e media
RUN mkdir -p /app/staticfiles /app/media

# Expõe a porta 8000
EXPOSE 8000

# Comando para rodar o servidor (usando Gunicorn)
CMD ["gunicorn", "core.wsgi:application", "--bind", "192.168.0.31:8000"]