# News Trading Bot — Entrar antes del dato

Coloca órdenes pendientes (buy-stop / sell-stop) alrededor del precio justo antes de la publicación de un dato económico, para que una de las dos ya esté en el mercado cuando el precio hace spike — en vez de perseguir el movimiento después.

## Cómo funciona

```
T - 5s  → Bot coloca BUY STOP + SELL STOP alrededor del precio
T + 0s  → Sale el dato (NFP, CPI, FOMC...)
T + 0.1s→ El mercado spike, UNA de las dos órdenes se activa
T + 0.2s→ Bot cancela la orden contraria
T + Xm  → SL o TP cierran el trade
```

## Requisitos

* MetaTrader 5 instalado en el ordenador / VPS (el paquete `MetaTrader5` de Python solo funciona junto al terminal nativo, que es Windows-only — usar Wine o una VPS Windows si se desarrolla en Linux/Mac)
* Cuenta en broker con spreads bajos: IC Markets, Pepperstone, FP Markets
* Python 3.11+

## Instalación

```bash
cd mt5_news_bot
pip install -r requirements.txt
cp .env.example .env
```

## Configuración (`.env`)

```
MT5_LOGIN=TU_NUMERO_CUENTA
MT5_PASSWORD=TU_PASSWORD
MT5_SERVER=ICMarkets-Demo   # Demo primero, siempre

SECONDS_BEFORE_NEWS=5    # Clave: 5 segundos antes del dato
STOP_LOSS_PIPS=15        # SL ajustado para volatilidad de noticias
TAKE_PROFIT_PIPS=30      # RR 1:2
LOT_SIZE=0.10            # Empezar pequeño
MAX_SPREAD_PIPS=3        # Si el spread supera esto, no se coloca la orden
DRY_RUN=true             # Simula fills sin tocar MT5 — para pruebas
```

`DRY_RUN=true` (o correr sin el paquete `MetaTrader5` instalado, p.ej. en Linux) activa un simulador en `mt5_client.py` que aleatoriamente dispara una de las dos patas, así se puede validar el flujo completo del bot sin una cuenta real conectada.

## Calendario económico

`news_calendar.py` calcula automáticamente NFP e ISM Manufacturing (caen en un día de la semana fijo cada mes). CPI, Retail Sales, GDP, FOMC, ECB y BOE **no** siguen una regla fija — hay dos formas de obtener esas fechas:

1. **Recomendado:** crear una API key gratuita en [finnhub.io](https://finnhub.io) y ponerla en `FINNHUB_API_KEY` — el bot la usa automáticamente para todos los eventos de alto impacto.
2. **Manual:** rellenar la lista `MANUAL_EVENTS` en `news_calendar.py` con las fechas oficiales de:
   - FOMC: federalreserve.gov/monetarypolicy/fomccalendars.htm
   - CPI / Retail Sales / GDP: bls.gov/schedule/news_release, census.gov, bea.gov/news/schedule
   - ECB: ecb.europa.eu/press/calendars/mgcgc
   - BOE: bankofengland.co.uk/monetary-policy-summary-and-minutes

Sin ninguna de las dos, solo se operan NFP e ISM.

## Uso

```bash
# Ver calendario de la semana
python news_calendar.py

# Arrancar el bot (usa DRY_RUN de .env)
python main.py
```

## Eventos que opera

* 🇺🇸 NFP (Non-Farm Payrolls) — primer viernes del mes
* 🇺🇸 CPI — mensual
* 🇺🇸 FOMC Rate Decision — 8 veces al año
* 🇺🇸 GDP, Retail Sales, ISM
* 🇪🇺 ECB Rate Decision
* 🇬🇧 BOE Rate Decision

Cada evento se mapea a los pares que expone (`config.EVENT_SYMBOLS`): USD → EURUSD/GBPUSD/USDJPY, EUR → EURUSD, GBP → GBPUSD.

## Flujo de estados

```
IDLE → (detecta evento) → WAITING → (N segundos antes) → ORDERS_PLACED
     → (una se dispara) → IN_TRADE → (SL o TP) → IDLE
```

Implementado en `bot.py` (`NewsTradingBot.run_event`), orquestado por `main.py` sobre los eventos que devuelve `news_calendar.get_events`.

## Archivos

```
config.py         Todos los settings — cuenta MT5, timing, riesgo, símbolos
news_calendar.py  Calendario económico (built-in + Finnhub opcional)
mt5_client.py     Wrapper sobre MetaTrader5 — conexión, cotizaciones, órdenes pendientes/posiciones
bot.py            Máquina de estados: straddle, cancelación del lado perdedor, espera de cierre
main.py           Bucle principal — arma el bot antes de cada evento
```

## Broker recomendado

Para que esto funcione el broker necesita:

* Spreads bajos en noticias (IC Markets Raw, Pepperstone Razor)
* Ejecución rápida (<50ms)
* Sin restricciones de news trading

## VPS (recomendado)

Para latencia mínima, usar un VPS cerca del servidor del broker:

* IC Markets: Sydney → VPS en AWS ap-southeast-2
* Pepperstone: London → VPS en AWS eu-west-2
* Latencia objetivo: <10ms al servidor del broker

## ⚠️ Advertencias

1. SIEMPRE probar en DEMO primero (mínimo 10 noticias)
2. El spread puede explotar justo antes del dato — el filtro `MAX_SPREAD_PIPS` lo detiene
3. Algunos brokers prohíben news trading — leer los ToS
4. El slippage en el fill puede ser >5 pips en noticias muy grandes (NFP)
5. Nunca correr en live sin haber validado en demo
6. Verificar las fechas de `MANUAL_EVENTS` / Finnhub contra la fuente oficial antes de operar — un dato mal calendarizado dispara la lógica en el momento equivocado

## Disclaimer

Este módulo es solo para fines educativos. No es asesoramiento financiero. El trading de noticias implica un riesgo alto de pérdida, incluyendo slippage y ejecución adversa en momentos de alta volatilidad. Úsalo bajo tu propio riesgo y siempre valida en cuenta demo antes de operar en real.
