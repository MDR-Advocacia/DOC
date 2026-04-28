# Plano de Correção — Deploy DOC no Coolify

**Data:** 2026-04-28
**Branch atual:** DOC-Apex
**Origem:** página de debug do Django vazando em produção (`doc.mdradvocacia.com` / `doc-lab.mdradvocacia.com`)

---

## Diagnóstico em uma frase

`DEBUG=True` está ativo em produção, e o `core/settings.py` ignora várias variáveis de ambiente que deveriam parametrizar o deploy (ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, headers de proxy TLS), o que torna o app frágil e inseguro atrás do Traefik do Coolify.

---

## Prioridades

| Nível | Descrição | Onde |
|------|-----------|------|
| **P0** | Fechar vazamento da página de debug e habilitar TLS corretamente atrás do Traefik | Coolify + `settings.py` |
| **P1** | Tornar `settings.py` parametrizável por env var (ALLOWED_HOSTS, CSRF, SECRET_KEY obrigatório) | `settings.py` |
| **P2** | Coerência de sessão, worker headless, healthcheck, dependências pinadas | `settings.py`, `Dockerfile`, `docker-compose.yml`, `requirements.txt` |
| **P3** | Hardening adicional (HSTS, SSL redirect, política de cache para escala) | `settings.py` |

---

## P0 — Fechar o vazamento (ação imediata)

### P0.1 — Corrigir env vars no painel do Coolify

No serviço `web` em **Coolify → Environment Variables**, defina/ajuste:

```
DEBUG=False
SECRET_KEY=<gerar uma nova chave forte de 50+ chars>
ALLOWED_HOSTS=doc.mdradvocacia.com,doc-lab.mdradvocacia.com
CSRF_TRUSTED_ORIGINS=https://doc.mdradvocacia.com,https://doc-lab.mdradvocacia.com
DJANGO_SECURE_PROXY=True
PROCESSOS_WORKER_HEADLESS=True
```

> Para gerar SECRET_KEY: `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`

### P0.2 — Fix mínimo no `settings.py`

Substituir o bloco atual (linhas 40-54) por:

```python
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
DEBUG = _env_as_bool('DEBUG', False)

if not SECRET_KEY:
    if DEBUG or RUNNING_TESTS:
        SECRET_KEY = 'doc-dev-secret-key-NOT-FOR-PROD'
    else:
        raise RuntimeError("SECRET_KEY não definida em produção")

def _csv_env(name, default):
    raw = os.environ.get(name, '')
    items = [x.strip() for x in raw.split(',') if x.strip()]
    return items or default

ALLOWED_HOSTS = _csv_env('ALLOWED_HOSTS', [
    "localhost", "127.0.0.1", "192.168.0.31", "doc.mdr.local",
])

CSRF_TRUSTED_ORIGINS = _csv_env('CSRF_TRUSTED_ORIGINS', [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://192.168.0.31:8000",
    "http://doc.mdr.local",
])

# Atrás de proxy reverso (Traefik no Coolify)
if _env_as_bool('DJANGO_SECURE_PROXY', False):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
```

E mudar a checagem booleana atual para usar a função existente:

```python
# Antes (linha 43):
DEBUG = os.environ.get('DEBUG') == 'True'  # frágil — só aceita "True" exato
# Depois:
DEBUG = _env_as_bool('DEBUG', False)        # aceita true/True/1/yes/on
```

### P0.3 — Verificar

Após redeployar:

```bash
curl -I https://doc.mdradvocacia.com/
# Deve retornar 200/302/etc., NUNCA mais a página de debug em erro 404/500
```

Forçar um 404 (ex: `curl https://doc.mdradvocacia.com/qualquer-coisa-que-nao-existe`) deve mostrar a página padrão "Not Found" do Django, sem dump de settings.

---

## P1 — Parametrização e robustez

### P1.1 — Tornar `dotenv` opcional em produção

Linha 21 carrega `.env` sempre. Se `.env` não existe na imagem (e não existe, pelo `.dockerignore`), `load_dotenv` retorna False silenciosamente — então é cosmético, mas explicitar deixa a intenção clara:

```python
if DEBUG or os.environ.get('LOAD_DOTENV') == '1':
    load_dotenv(BASE_DIR / ".env")
```

> Coloque essa lógica DEPOIS de uma checagem inicial só de DEBUG via env, para evitar dependência circular.

### P1.2 — Configuração de email via env (se for usar)

Hoje os defaults apontam para `localhost:25` — não funciona em container Coolify. Se for enviar email (reset de senha, p.ex.), defina no Coolify:

```
EMAIL_HOST=smtp.seuprovedor.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=DOC <noreply@mdradvocacia.com>
```

Se NÃO for usar agora, troque o backend para console em dev e dummy em prod, evitando timeouts:

```python
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'django.core.mail.backends.dummy.EmailBackend'
)
```

### P1.3 — Coerência de sessão

`settings.py` linhas 176-185 definem três regras conflitantes. Decidir uma política e manter:

**Opção A — sessão de 30 min, persiste se navegador fechar (típico de SaaS):**
```python
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # mudar
```

**Opção B — sessão acaba ao fechar navegador (mais seguro para escritório):**
```python
SESSION_COOKIE_AGE = 1800              # vira teto absoluto
SESSION_SAVE_EVERY_REQUEST = False     # tempo absoluto, não desliza
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
```

Hoje está num híbrido inconsistente: `EXPIRE_AT_BROWSER_CLOSE=True` faz o cookie virar de sessão (sem `Max-Age`), o que **anula** o `COOKIE_AGE=1800`. Recomendo **Opção A** para um app interno de escritório.

---

## P2 — Container e dependências

### P2.1 — Pinar dependências

`requirements.txt` atual usa `Django>=5.0` e várias sem versão. Build pode quebrar a qualquer momento. Gerar lock:

```bash
# No venv local com tudo funcionando:
pip freeze > requirements.lock.txt
# E no Dockerfile mudar para: COPY requirements.lock.txt /app/requirements.txt
```

Ou pelo menos pinar as raízes:

```
Django>=5.2,<5.3
psycopg2-binary==2.9.9
docxtpl==0.20.1
gunicorn==23.0.0
whitenoise==6.8.2
python-dotenv==1.0.1
python-docx==1.1.2
djangorestframework==3.15.2
drf-yasg==1.21.7
pypdf==4.3.1
openpyxl==3.1.5
```

### P2.2 — Healthcheck

Adicionar uma view leve em `core/urls.py`:

```python
from django.http import JsonResponse
from django.urls import path

urlpatterns = [
    # ... rotas existentes
    path('healthz/', lambda r: JsonResponse({'ok': True})),
]
```

E no `Dockerfile`:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/').status==200 else 1)"
```

No Coolify, configurar o healthcheck path como `/healthz/`.

### P2.3 — Worker headless

`PROCESSOS_WORKER_HEADLESS = False` no dump indica que a env var não está chegando no container web (o dump é do `web`, não do `processos-worker`, mas a settings é compartilhada). Confirmar no painel do Coolify e no `docker-compose.yml` (já está `${PROCESSOS_WORKER_HEADLESS:-true}` para o worker, mas o `web` pega do `.env` e depende do que estiver lá).

Mais simples: mudar o default no `settings.py` para `True`:

```python
PROCESSOS_WORKER_HEADLESS = _env_as_bool('PROCESSOS_WORKER_HEADLESS', True)
```

### P2.4 — Migrate como entrypoint dedicado

Hoje o `docker-compose.yml` faz `migrate && collectstatic && gunicorn` no comando do `web`. Em Coolify, isso roda **toda vez que o container sobe**, e se duas réplicas subirem juntas, há race condition no migrate.

Recomendação: criar `scripts/entrypoint.sh`:

```bash
#!/usr/bin/env sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --access-logfile - --error-logfile -
```

E no Dockerfile:
```dockerfile
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]
```

Para múltiplas réplicas, mover migrate para um job separado (Coolify suporta "Init Command").

---

## P3 — Hardening adicional

Depois que P0-P2 estiver estável e validado em `doc-lab.mdradvocacia.com`:

```python
# Só ligar quando tiver certeza que TUDO vai por HTTPS
if not DEBUG and _env_as_bool('DJANGO_SECURE_PROXY', False):
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000          # 1 ano — começar com 3600 e ir subindo
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = False              # só ligar quando submeter ao preload list
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
```

> ⚠️ HSTS é "uma via só" — o navegador lembra. Comece com `SECURE_HSTS_SECONDS=3600` (1h) e suba gradualmente.

### Cache para escala (se for escalar)

Se em algum momento subir 2+ réplicas no Coolify:

```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://redis:6379/1'),
    }
}
```

E adicionar serviço `redis` no `docker-compose.yml`. Sem isso, o throttling do DRF e o cache de view ficam inconsistentes entre réplicas.

---

## Risco lateral — chave OpenAI

O `.env` local tem uma `CALCULO_LLM_API_KEY` real:

```
CALCULO_LLM_API_KEY=sk-proj-5RejNN1udyL-fiDC...
```

O `.gitignore` exclui `.env`, mas:

1. **Verificar histórico:**
   ```bash
   git log --all --full-history -- .env
   git log --all -p -S 'sk-proj-5RejNN1udyL'
   ```
2. Se aparecer **qualquer commit**, a chave está exposta — **rotacione no painel OpenAI imediatamente** e use a nova só via env var no Coolify.
3. Mesmo que não apareça, considere rotacionar por higiene (a chave já foi compartilhada em chat).

---

## Checklist de execução

### Imediato (P0) — fecha o vazamento hoje
- [ ] Definir `DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DJANGO_SECURE_PROXY=True` no painel Coolify (web e processos-worker)
- [ ] Aplicar patch P0.2 em `core/settings.py` (env-driven + proxy header)
- [ ] Commit + push na branch `DOC-Apex` (ou criar `fix/coolify-debug`)
- [ ] Redeploy no Coolify
- [ ] Validar: forçar 404, conferir que NÃO mostra página de debug
- [ ] Validar: login HTTPS funciona, cookies marcados como Secure no DevTools

### Curto prazo (P1)
- [ ] Política de sessão única e coerente (Opção A)
- [ ] Default de `PROCESSOS_WORKER_HEADLESS` para True
- [ ] Configurar SMTP real OU mover para backend dummy

### Médio prazo (P2)
- [ ] Pinar versões em `requirements.txt`
- [ ] Healthcheck `/healthz/` + `HEALTHCHECK` no Dockerfile
- [ ] `entrypoint.sh` separado
- [ ] Verificar histórico git por leak da chave OpenAI; rotacionar

### Longo prazo (P3)
- [ ] HSTS gradual em `doc-lab` primeiro
- [ ] Decisão sobre escala (1 réplica → manter LocMem; 2+ → Redis)

---

## Apêndice — Como eu testaria localmente antes de subir

```bash
# Simular o ambiente Coolify localmente
docker compose down
DEBUG=False SECRET_KEY=teste-prod-local-xxxxxx \
  ALLOWED_HOSTS=localhost \
  CSRF_TRUSTED_ORIGINS=http://localhost:8888 \
  docker compose up --build

# Em outro terminal:
curl -I http://localhost:8888/
curl -I http://localhost:8888/rota-inexistente   # deve dar 404 sem dump
```

Se passar nesse teste, sobe com confiança no `doc-lab` antes do `doc.mdradvocacia.com`.
