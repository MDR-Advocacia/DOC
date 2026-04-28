# Deploy do DOC

## Variaveis obrigatorias

O `docker-compose.yml` sobe tres servicos:

- `db`: banco Postgres.
- `web`: aplicacao Django.
- `processos-worker`: worker que busca e baixa pecas processuais.

O `processos-worker` conversa com o `web` por API interna. Para isso, os dois precisam compartilhar o mesmo token:

```env
PROCESSOS_WORKER_TOKEN=cole-aqui-um-token-longo-e-aleatorio
```

Se voce usa arquivo `.env` no servidor, adicione essa linha ao `.env` de producao.
Se voce usa painel de deploy, adicione `PROCESSOS_WORKER_TOKEN` nas variaveis de ambiente do servico.

Para gerar um token:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Depois de configurar, suba/reinicie:

```bash
docker compose up -d --build
```

## Observacao

O valor de `PROCESSOS_WORKER_TOKEN` precisa ser exatamente igual para o `web` e para o `processos-worker`.
No `docker-compose.yml`, ambos leem o mesmo `.env`, entao basta declarar a variavel uma vez nesse arquivo.
