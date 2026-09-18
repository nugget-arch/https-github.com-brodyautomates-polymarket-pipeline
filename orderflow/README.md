# Order Flow Terminal — velas + footprint + **order book L2** en vivo

Terminal de **order flow** para cripto, con estética tipo ATAS / DeepCharts y
datos **reales** de Binance (REST para el seed + **WebSocket** para el streaming
en vivo, incluido el **order book L2**).

![preview](preview.png)

## Dos vistas

- **Velas** (por defecto, como la imagen de referencia): velas limpias + **perfil
  de volumen** (azul sobre el vPOC, rojo debajo) + **burbujas de delta** por vela +
  **vPOC / VAH / VAL** + **VWAP** + pie con `Lots | Δ`.
- **Footprint**: cluster chart con volumen **bid × ask** por nivel de precio
  (números al hacer zoom, heatmap al alejar), con imbalances resaltados, POC y
  strip de delta.

Cambias entre ellas con el selector **Velas / Footprint** (o `?mode=footprint`).

## Order book L2 (nuevo)

- **DOM ladder** en el lateral: bids/asks reales por nivel, tamaño con barra,
  spread, y los niveles grandes resaltados. Marca **❄ iceberg** y **◆ absorción**.
- **Histograma de profundidad** en el borde derecho del gráfico: la liquidez
  en reposo (bid/ask) alineada al precio.
- **Imbalance del libro** (bid vs ask) en la cabecera del panel.
- Se siembra con un snapshot REST (`/api/depth`) y se mantiene vivo con el stream
  `@depth20@100ms`.

## Detecciones

Ahora hay **dos fuentes** de señales, combinadas en el feed lateral:

| Señal | Fuente | Cómo se detecta |
|---|---|---|
| **Iceberg** (real) | **L2 + trades** | Un nivel donde el volumen **ejecutado** supera con creces el tamaño que el libro llegó a **mostrar** (se recarga) → orden oculta. |
| **Absorción** (real) | **L2 + trades** | Un nivel de reposo **grande** que aguanta agresión fuerte sin romperse. |
| **Imbalance diagonal** | footprint | `ask[n]` vs `bid[n-1]` (compra) / `bid[n]` vs `ask[n+1]` (venta), ratio ≥ 300%. |
| **Stacked imbalance** | footprint | ≥ 3 imbalances consecutivos en la misma dirección. |

> El iceberg y la absorción con **L2** son detecciones de verdad (comparan lo
> ejecutado contra lo que el libro mostró), no aproximaciones solo-por-trades.

## De dónde salen los datos (Binance, sin API key)

| Qué | Fuente |
|---|---|
| Velas + delta por vela | `klines` (incluye `takerBuyBaseVolume`) |
| Perfil / vPOC / VAH / VAL | derivado de las velas |
| Footprint (bid/ask por nivel) | `aggTrades` (seed) + `@aggTrade` (live) |
| **Order book L2** | `/api/v3/depth` (seed) + `@depth20@100ms` (live) |

El servidor Python solo arma el **seed** (footprint + snapshot de profundidad) y lo
cachea unos segundos; el streaming en vivo (trades, klines y **libro**) lo hace el
navegador directo contra Binance. Si el WebSocket está bloqueado, cae a *polling* REST.

## Cómo correrlo

Solo **Python 3.8+**, sin dependencias externas:

```bash
python3 orderflow/server.py     # http://localhost:8787
```

Deep-links: `?symbol=ETHUSDT&tf=5m&candles=40&mode=footprint`.
Toggles: **Perfil · VWAP · L2 Depth · Delta**. Variable `ORDERFLOW_PORT`.

## Endpoints

- `GET /api/seed?symbol=&interval=&candles=&fp=` — OHLC + perfil + VA + footprint real.
- `GET /api/depth?symbol=&limit=` — snapshot del order book L2.
- `GET /api/chart`, `GET /api/footprint` — endpoints simples de versiones previas.

## Límites del prototipo (honestos)

- El stream `@depth20` da los **20 niveles** más cercanos al spread; para un
  heatmap de profundidad ancho (estilo Bookmap) haría falta el libro completo
  (`depth` con `limit` alto + gestión de diffs), más pesado.
- La detección de iceberg/absorción usa esa ventana de 20 niveles; es sólida cerca
  del precio, no para órdenes muy lejanas del spread.
- Sin persistencia ni cuenta: es una demo técnica.

## Siguientes pasos posibles

- Libro completo con diffs (`@depth` incremental) para un **heatmap de liquidez**
  histórico tipo Bookmap.
- Alertas (push/webhook) sobre iceberg, absorción y stacked imbalance.
- Grabar y reproducir sesiones (replay del footprint + libro).
