# Order Flow / Footprint — prototipo (BTC, datos reales)

Visor de **order flow** estilo footprint para cripto, inspirado en los charts de
ES/futuros pero usando datos **reales y gratuitos** de Binance.

![preview](preview.png)

## Qué muestra

- **Velas** (OHLC) del par e intervalo elegidos.
- **Perfil de volumen** a la izquierda, separado en volumen agresor comprador
  (verde) y vendedor (rojo).
- **vPOC / VAH / VAL** — punto de control de volumen y el *value area* del 70%.
- **Burbujas de delta** por vela: `delta = volumen taker-buy − volumen taker-sell`
  (verde = presión compradora, rojo = vendedora). El tamaño escala con |delta|.
- **Footprint real por nivel de precio**: haz click en cualquier vela para ver el
  desglose buy/sell tick a tick de ese minuto (calculado desde `aggTrades`, usando
  el lado agresor de cada operación).

## De dónde salen los datos

Todo viene del endpoint público de Binance `data-api.binance.vision` (sin API key):

| Señal | Fuente |
|---|---|
| Velas + delta por vela | `klines` (incluye `takerBuyBaseVolume`) |
| Perfil de volumen / vPOC / VAH / VAL | derivado de las velas |
| Footprint por nivel de precio | `aggTrades` (campo `m` = lado agresor) |

> `m == false` → el comprador es *taker* → **compra agresiva**
> `m == true`  → el comprador es *maker* → **venta agresiva**

## Cómo correrlo

Solo necesitas **Python 3.8+** (sin dependencias externas):

```bash
python3 orderflow/server.py
# abre http://localhost:8787
```

Variables opcionales:

- `ORDERFLOW_PORT` — puerto (por defecto `8787`).

## Endpoints

- `GET /api/chart?symbol=BTCUSDT&interval=1m&candles=90`
  → velas, perfil de volumen, vPOC/VAH/VAL, delta acumulado.
- `GET /api/footprint?symbol=BTCUSDT&interval=1m&openTime=<ms>`
  → footprint real (buy/sell por nivel) de esa vela.

Pares incluidos en la UI: BTC, ETH, SOL, BNB (contra USDT). Cualquier símbolo
spot de Binance funciona vía la API.

## Límites del prototipo

- Es una demo, no un producto: no hay persistencia ni streaming por WebSocket
  (refresca por polling; hay un toggle *Auto 5s*).
- El perfil de volumen del chart completo se aproxima distribuyendo el volumen de
  cada vela en su rango high-low. El footprint por-vela (al hacer click) **sí** es
  tick a tick real.
- Para tiempo real de baja latencia y profundidad completa conviene pasar a los
  WebSockets de Binance (`@aggTrade`, `@kline`).

## Siguientes pasos posibles

- Streaming en vivo con WebSocket (delta rodante de la vela en curso).
- Imbalance/stacked-imbalance y detección de absorción.
- Perfiles por sesión (VPOC diario, naked POCs, LVN/HVN).
- Alertas sobre delta divergente o barridos de VAH/VAL.
