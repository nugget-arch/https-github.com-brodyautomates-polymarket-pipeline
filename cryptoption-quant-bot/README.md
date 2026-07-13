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

Fase 3 (features/labels/modelos): `quant_engine.features` con features 100%
**causales** (retornos multi-horizonte, EMA+pendiente, RSI, ATR, vol realizada,
Bollinger z, pendiente de regresión, cuerpo/mechas/posición de vela, volumen
relativo, spread y su cambio, proxies de flujo, tiempo cíclico, régimen de
vol/tendencia) y **`FeatureAvailabilityAudit`** (columnas de entrada, lookback,
shift, riesgo de leakage por feature). `quant_engine.labels` (CALL/PUT con
vencimientos/latencia/empates, sin cruzar sesiones ni huecos). Modelos
Random/Trend/MeanReversion + **logística regularizada** con calibración
temporal (Platt/isotónica, nunca sobre el test). **Tests anti-leakage**
incluidos, entre ellos que *mutar el futuro no cambia el pasado*.

Fase 4 (backtest/riesgo): backtester **event-driven** (eventos tipados,
payout variable U(base±jitter) con suelo, latencia, rechazos de bróker, máximo
una operación por activo, empates configurables; PnL con el payout **real** de
cada operación, nunca retornos porcentuales). Métricas completas de binarias
(win rate, break-even, edge, VE, profit factor, drawdown y su duración, rachas,
Brier, log loss, **ECE**, calibración, IC de win rate, p-valor, %NO_TRADE).
**`RiskManager` anti-martingala por construcción** (el stake nunca sube tras
perder — verificado por test), con límite de pérdida diaria, cool-off por
rachas, tope por sesión, kill switch y reducción de exposición por drawdown.
Monte Carlo de probabilidad de ruina y `PaperBroker` con ledger.

Fase 5 (validación): **walk-forward** con ventanas train/val/test no solapadas,
**purga por horizonte** (una muestra de train cuyo horizonte solape validación
se descarta) y **embargo** temporal; **holdout final bloqueado** (hash de
config + confirmación explícita, un solo uso, imposible reutilizar para seguir
optimizando); **selección de umbral desde la incertidumbre de validación**
(Wilson), nunca del test; runner que ejecuta cada combo modelo×vencimiento y
aplica **Benjamini-Hochberg** entre combos para que ninguna combinación
"rentable por suerte" sobreviva. Sobre ruido puro, ningún combo pasa la
corrección — verificado por test.

El resto (paper/shadow/manual en vivo, CandidateGate completo, informes,
registro de experimentos, seguridad) se incorpora en fases siguientes.

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
