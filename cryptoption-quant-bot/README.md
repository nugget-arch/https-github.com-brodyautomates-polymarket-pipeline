# cryptoption-quant-bot

Plataforma web de investigación cuantitativa para opciones binarias que
**solo** investiga, valida y ejecuta operaciones **simuladas** (paper), en
**modo sombra** (shadow) o de **confirmación manual**. No se conecta a ningún
bróker por medios no oficiales y **no ejecuta con dinero real**.

> **No promete rentabilidad.** Su objetivo es demostrar o refutar, de forma
> honesta y reproducible, si existe una ventaja estadística operable. Un
> resultado perfectamente válido es:
> **"NO SE HA DEMOSTRADO UNA VENTAJA ESTADÍSTICA OPERABLE"**.

## Restricciones absolutas (por diseño, verificadas en código)

- Sin ingeniería inversa de CryptOption, endpoints privados, WebSockets
  internos, cookies/tokens de sesión, headers autenticados, Selenium /
  Playwright / Puppeteer contra su web, captura de tráfico, bypass de CAPTCHA,
  antifingerprint ni antidetección.
- Sin ejecución con dinero real. `OfficialCryptOptionBrokerAdapter` es un
  *placeholder* cuyos métodos de ejecución lanzan `OfficialApiUnavailableError`.
- Sin martingala, soros, antimartingala ni sizing de recuperación de pérdidas.
- La captura aportada es **solo referencia visual**; su win rate no es objetivo
  ni evidencia.

## Estado: Fase 2 (datos en tiempo real)

Fase 1 (scaffold): monorepo · Docker Compose · FastAPI · Next.js · PostgreSQL ·
Redis · auth single-user con roles · modelo de dominio · dashboard estático.

Fase 2 (datos): `quant_engine.data` con esquema normalizado y providers
(Sintético, Histórico CSV/Parquet, Replay determinista, Import OTC manual,
Binance público solo-cripto), validación de calidad con **Polars** (sin
interpolación ni relleno con futuro), agregación de velas **causal** (solo
emite barras cerradas), **WebSocket propio** (envelope `{seq,ts,type,payload}`,
IDs de secuencia, heartbeat, autenticación por cookie, detección de huecos),
feed de mercado sobre bus de eventos, y **gráfico de precio en tiempo real** en
`/trading` con reconexión y recuperación de estado vía REST.

El motor cuantitativo restante se incorpora por fases portando el proyecto ya
probado `otc_lab/` del repositorio raíz.

Objetivo de runtime: Python 3.12 (funciona en ≥3.11), Node ≥20.

## Arranque rápido

```bash
cp .env.example .env
make up            # docker compose: postgres + redis + api + web
make migrate       # alembic upgrade head
# api  -> http://localhost:8000/health
# web  -> http://localhost:3000/dashboard
```

Desarrollo sin Docker:

```bash
make install       # deps de api + web
make dev-api       # uvicorn (usa DATABASE_URL de .env)
make dev-web       # next dev
make test          # pytest + vitest
make lint          # ruff + mypy + tsc
```

## Estructura

```
apps/api    FastAPI async (orquestación, REST + WebSocket, sin matemática)
apps/web    Next.js/TS (solo habla con nuestro backend)
packages/quant_engine   motor determinista (features, labels, validación…)
config      configuración por entorno / experimentos
migrations  Alembic
datasets    raw / validated / synthetic
reports     informes generados
```

Ver `../` (repo raíz) `otc_lab/` para el motor de investigación de referencia.
