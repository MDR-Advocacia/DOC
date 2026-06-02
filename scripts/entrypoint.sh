#!/usr/bin/env sh
# Entrypoint padrão do serviço web (DOC).
# - Roda migrações (idempotente).
# - Coleta estáticos para o WhiteNoise servir.
# - Sobe o Gunicorn vinculado em 0.0.0.0:8000.
#
# Em escala (2+ réplicas no Coolify), mover o `migrate` para um job
# pré-deploy ("Init Command" no painel) para evitar race condition.
set -e

echo ">> [entrypoint] aplicando migrations"
python manage.py migrate --noinput

echo ">> [entrypoint] coletando arquivos estáticos"
python manage.py collectstatic --noinput

echo ">> [entrypoint] iniciando Gunicorn"
exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --access-logfile - \
    --error-logfile -
