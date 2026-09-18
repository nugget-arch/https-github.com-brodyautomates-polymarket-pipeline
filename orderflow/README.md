# Order Flow Terminal — footprint en vivo (BTC, datos reales)

Visor de **order flow / footprint** en tiempo real para cripto, con estética y
funciones tipo **ATAS / DeepCharts**, usando datos **reales y gratuitos** de
Binance (REST para el seed + **WebSocket** para el streaming en vivo).

![preview](preview.png)

## Qué hace

- **Footprint / cluster chart**: cada vela muestra, por nivel de precio, el
  volumen **bid × ask** (venta agresiva a la izquierda en rojo, compra agresiva
  a la derecha en verde), con las celdas sombreadas por volumen.
- **Streaming en vivo por WebSocket** directo a Binance: la vela en curso se
  actualiza trade a trade (`@aggTrade` + `@kline`). Si el WebSocket está
  bloqueado, cae automáticamente a *polling* REST.
- **Perfil de volumen** de la sesión visible + **vPOC / VAH / VAL** (value area 70%).
- **Delta por vela** (strip inferior) y **CVD** (delta acumulado) en subpanel.
- **Panel de la vela en curso**: precio, delta, buy/sell vol, CVD.
- **Feed de señales** de order flow en el lateral, en vivo.

## Detecciones "pro" incluidas

| Señal | Cómo se detecta |
|---|---|
| **Imbalance (diagonal)** | Compara `ask[nivel]` vs `bid[nivel-1]` (compra) y `bid[nivel]` vs `ask[nivel+1]` (venta). Se marca cuando el ratio ≥ **300%**. |
| **Stacked imbalance** | ≥ **3** imbalances consecutivos en la misma dirección → presión fuerte (bracket en el borde de la vela + señal). |
| **Absorción** | Volumen fuerte y muy unilateral en un extremo de la vela que **no** logra mover el precio (el lado pasivo absorbe). Marca **A**. |
| **Iceberg** | Un único nivel que se lleva una porción desproporcionada del volumen de la vela (outlier estadístico), típico de una orden límite oculta que se recarga. Marca **❄**. |

> `m == false` (comprador es *taker*) → **compra agresiva** (ask)
> `m == true`  (comprador es *maker*) → **venta agresiva** (bid)

## De dónde salen los datos

Todo del endpoint público de Binance (sin API key):

| Señal | Fuente |
|---|---|
| Seed histórico (footprint real de las velas recientes) | `data-api.binance.vision` · `klines` + `aggTrades` |
| Live (vela en curso, trade a trade) | `wss://data-stream.binance.vision` · `@aggTrade` + `@kline` |

El servidor Python solo arma el **seed** (footprint real de las últimas N velas) y
lo cachea unos segundos; el streaming en vivo lo hace el navegador directo contra
Binance, así que el backend queda ligero.

## Cómo correrlo

Solo **Python 3.8+**, sin dependencias externas:

```bash
python3 orderflow/server.py
# abre http://localhost:8787
```

Variables opcionales: `ORDERFLOW_PORT` (por defecto `8787`).

Controles en la UI:

- **Par**: BTC, ETH, SOL, BNB, XRP (cualquier símbolo spot de Binance sirve vía API).
- **TF**: 1m / 3m / 5m / 15m.
- **Velas**: cuántas velas de footprint mostrar. Con pocas velas se ven los
  **números** por nivel; con muchas, pasa a modo *heatmap* (celdas por intensidad).
- **Toggles**: Números · Imbalance · Absorción · Iceberg.

## Endpoints del servidor

- `GET /api/seed?symbol=BTCUSDT&interval=1m&candles=90&fp=18`
  → OHLC + perfil + vPOC/VAH/VAL + footprint real (bid/ask por nivel) de las
  últimas `fp` velas. Compacto: los niveles vienen como `[idx, bid, ask]` donde
  `price = idx * basetick`.
- `GET /api/chart` y `GET /api/footprint` — endpoints simples de la v1 (siguen ahí).

## Límites del prototipo (honestos)

- El **iceberg** se aproxima solo desde el flujo de trades (sin order book L2):
  detecta niveles que absorben un volumen anómalo, que suele ser una orden oculta
  que se recarga — pero para confirmarlo de verdad hace falta profundidad (L2).
- La **absorción** es heurística (volumen unilateral en un extremo + rechazo del
  precio), no una lectura de libro.
- El seed histórico depende de `aggTrades` (velas recientes); no reconstruye
  footprint de días atrás.
- No hay persistencia ni cuenta de usuario: es una demo técnica.

## Siguientes pasos posibles

- **Order book L2** (`@depth`) para icebergs y absorción confirmados con libro.
- Perfiles por sesión (naked POCs, HVN/LVN), VWAP y bandas.
- Alertas configurables (push/webhook) sobre stacked imbalance, absorción, etc.
- Persistir el footprint para reproducir sesiones pasadas.
