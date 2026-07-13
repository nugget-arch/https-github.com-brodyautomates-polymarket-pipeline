# CLAUDE.md — cryptoption-quant-bot

Guía para agentes que trabajen en este monorepo.

## Qué es y qué NO es

Plataforma de **investigación** de binarias con ejecución **solo** simulada
(paper), sombra (shadow) o confirmación manual. Objetivo: demostrar o refutar
una ventaja estadística de forma honesta y reproducible. **Nunca** prometer
rentabilidad; un veredicto negativo es un resultado válido y esperado.

## Líneas rojas (no cruzar jamás)

- Nada de ingeniería inversa, endpoints privados, WebSockets internos,
  cookies/tokens de CryptOption, Selenium/Playwright/Puppeteer contra su web,
  captura de tráfico, bypass CAPTCHA, antidetección.
- Ejecución real deshabilitada. `OfficialCryptOptionBrokerAdapter` solo lanza
  `OfficialApiUnavailableError`; sin URLs/endpoints/tokens inventados.
- Sin martingala/soros/antimartingala/recuperación de pérdidas. El stake nunca
  sube por haber perdido.
- No inventar resultados ni declarar tests ejecutados si no se ejecutaron.
- No elegir estrategia/umbral mirando el holdout final.

## Arquitectura

Monolito modular. `apps/api` orquesta y no hace matemática; `packages/quant_engine`
hace toda la cuántica y no sabe de web; `apps/web` solo habla con nuestro
backend. Postgres = operacional; Redis = tiempo real/efímero; DuckDB =
experimentos.

## Comandos

`make install | up | migrate | dev-api | dev-web | test | lint | build`.
Tras cada fase: ejecutar tests + ruff + mypy + tsc + build y reportar salidas
**reales**. No avanzar de fase sin aprobación.

## Estilo

Python 3.12 objetivo, tipado estricto (mypy), Ruff. TS estricto. Nombres y
densidad de comentarios como el código vecino.
