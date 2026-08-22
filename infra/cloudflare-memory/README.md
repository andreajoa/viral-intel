# Viral Intel Memory — Cloudflare Worker + D1

Backend durável da memória longitudinal do Viral Intel 5. O Streamlit continua sendo a interface e o motor de análise; este Worker fornece uma API pequena, autenticada e persistente sobre D1.

## Arquitetura

`Streamlit -> HTTPS assinado por HMAC -> Worker -> D1`

A URL do Worker não é suficiente para acessar os dados. Todas as rotas `/v1/*` exigem `X-VI-Timestamp` e `X-VI-Signature`; a assinatura cobre timestamp, método, caminho/query e corpo exato. Requisições com mais de 5 minutos são rejeitadas.

## Provisionamento

1. Instale dependências: `npm install`
2. Autentique o Wrangler: `npx wrangler login`
3. Crie o banco: `npx wrangler d1 create viral-intel-memory`
4. Copie o `database_id` retornado para `wrangler.jsonc`.
5. Crie um segredo longo e aleatório e salve no Worker: `npx wrangler secret put API_SECRET`
6. Aplique migrations: `npm run db:migrate:remote`
7. Valide: `npm run check`
8. Faça deploy: `npm run deploy`
9. No Streamlit Secrets configure o mesmo segredo e a URL HTTPS do Worker:
   - `CLOUDFLARE_MEMORY_URL="https://...workers.dev"`
   - `CLOUDFLARE_MEMORY_SECRET="..."`
   - `ENABLE_PERSISTENCE="true"`

Nunca coloque `API_SECRET` ou `CLOUDFLARE_MEMORY_SECRET` no Git.

## Rotas

- `GET /health` — health check e versão do schema; não retorna dados do usuário.
- `POST /v1/reports` — salva snapshot completo de uma análise.
- `GET /v1/reports/comparable` — recupera histórico comparável para baseline/Content Twins.
- `GET /v1/posts/timeline` — recupera snapshots cronológicos do mesmo post.
- `POST /v1/experiments` — registra experimento.
- `POST /v1/experiments/:id/complete` — fecha experimento com resultado.

O SQLite local continua disponível como fallback e usa o mesmo contrato lógico.
