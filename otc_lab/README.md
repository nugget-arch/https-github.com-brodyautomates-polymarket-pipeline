# otc_lab — plataforma de investigación cuantitativa para opciones binarias OTC

Plataforma **reproducible** para determinar, mediante pruebas estadísticas, si
existe alguna ventaja real y persistente en datos OTC de opciones binarias.

> **Este proyecto no promete rentabilidad.** Su resultado más probable —y
> perfectamente válido— es el veredicto:
> **“NO SE HA DEMOSTRADO UNA VENTAJA ESTADÍSTICA OPERABLE”.**
> Está diseñado para poder llegar a esa conclusión con honestidad, no para
> fabricar curvas de equity bonitas.

## Límites deliberados (no negociables)

* **Solo datos históricos + paper trading / modo shadow.**
* **La ejecución real está deshabilitada** (`otc_lab.EXECUTION_ENABLED = False`,
  hard-coded). Cualquier intento lanza `ExecutionDisabledError`.
* **Sin conexión a Pocket Option**: nada de endpoints privados, WebSockets por
  ingeniería inversa, Selenium/automatización del navegador, captura de
  cookies, evasión de CAPTCHA, anti-detección, huellas falsificadas ni
  almacenamiento de credenciales.
* `BrokerAdapter` es únicamente una interfaz abstracta preparada para una
  **futura API oficial y documentada**, si algún día existe.
* **Prohibición absoluta de martingala**, soros y cualquier sizing que
  dependa de pérdidas anteriores (verificado por test).
* Sin redes neuronales hasta que modelos sencillos demuestren ventaja fuera
  de muestra.

## Instalación

```bash
cd otc_lab
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]          # añade [lgbm] si quieres LightGBM opcional
```

O con Docker:

```bash
docker build -t otc-lab .
docker run --rm otc-lab        # datos sintéticos + tests + investigación
```

Python objetivo: 3.12 (funciona en ≥3.11).

## Uso

```bash
# 1) datos sintéticos de ejemplo (random walk honesto por defecto)
python -m otc_lab.cli synth --out data/sample

#    control positivo: inyecta autocorrelación para verificar que el pipeline
#    SÍ detecta una ventaja cuando existe de verdad
python -m otc_lab.cli synth --out data/sample_edge --edge 0.35

# 2) validación de calidad de datos (timestamps, OHLC, duplicados, huecos, tz)
python -m otc_lab.cli validate --config config/default.yaml

# 3) investigación completa: walk-forward + backtest + estadística + informe
python -m otc_lab.cli research --config config/default.yaml

# 4) paper trading / shadow sobre histórico reproducido con reloj simulado
python -m otc_lab.cli paper --asset EURUSD_OTC --strategy logistic --mode shadow
python -m otc_lab.cli verify-journal --path artifacts/journal.jsonl

# 5) prueba final BLOQUEADA (una sola vez, al congelar la investigación)
#    requiere data.holdout_unlocked: true en el YAML *y* el flag explícito
python -m otc_lab.cli holdout --config config/default.yaml --i-am-done-researching

# tests
pytest
```

Con datos reales propios: exporta velas OHLC a CSV/Parquet con columnas
`timestamp, open, high, low, close[, volume][, asset]` y apunta `data.paths`
del YAML a esos ficheros. Los activos OTC se identifican por el sufijo `_otc`
en el nombre (o columna explícita `is_otc`) y **nunca se mezclan** con
mercados regulares en los desgloses.

## Árbol del proyecto

```
otc_lab/
├── pyproject.toml            # deps, tipado estricto, pytest
├── Dockerfile
├── config/default.yaml       # configuración completa del experimento
├── otc_lab/
│   ├── config.py             # modelos Pydantic + break_even_win_rate
│   ├── logging_setup.py      # logging estructurado JSON
│   ├── pipeline.py           # orquestación + criterios de veredicto
│   ├── cli.py                # synth / validate / research / paper / holdout
│   ├── data/                 # loader CSV-Parquet, validación, resampling
│   │   └── synthetic.py      #   generador sintético (con control positivo)
│   ├── features/engine.py    # features 100% causales (test de no-lookahead)
│   ├── labels/binary.py      # CALL/PUT, vencimientos 1/2/3/5, latencia, empates
│   ├── strategies/           # random / trend / meanrev / logística / LGBM opc.
│   ├── validation/           # walk-forward, purga+embargo, bootstrap, BH
│   ├── backtest/             # simulador event-driven, métricas, Monte Carlo
│   ├── risk/manager.py       # 0.25%/op, límites diarios, kill switch, NO martingala
│   ├── paper_trading/        # replayer con reloj simulado + journal inmutable
│   ├── broker/adapter.py     # BrokerAdapter abstracto (ejecución deshabilitada)
│   ├── experiments/registry.py  # registro SQLite de experimentos
│   └── report/builder.py     # informe MD+HTML con gráficas
└── tests/                    # unitarios + integración (control negativo y positivo)
```

## Matemática del problema

Con payout `b`, una operación ganadora paga `stake * b` y una perdedora
pierde `stake`. La tasa de acierto de equilibrio es:

```
break_even_win_rate = 1 / (1 + payout)      # payout 0.80 → 55.56 %
```

El umbral de decisión se deriva del **payout mínimo** configurado, un margen
de seguridad y la incertidumbre medida en validación — nunca del conjunto de
test. Solo se emite CALL si `P(subida) ≥ umbral` y PUT si
`P(subida) ≤ 1 − umbral`; en la zona intermedia **no se opera**.

## Cómo evita el autoengaño

| Trampa clásica | Contramedida |
|---|---|
| Look-ahead en features | Features causales + test de invarianza por truncado |
| Leakage entre operaciones solapadas | Purga por horizonte + embargo temporal |
| Umbral elegido mirando el test | Umbral = f(payout mínimo, margen, IC de validación) |
| Probar 100 combos y quedarse el mejor | Corrección Benjamini-Hochberg / Bonferroni |
| Sobreajuste al pasado | Walk-forward + holdout final bloqueado de un solo uso |
| Muestras pequeñas convincentes | Mínimo 1.000 operaciones OOS + IC del 95% |
| Correlación serial ignorada | Bootstrap por bloques |
| “Recuperar” pérdidas | Martingala prohibida y verificada por test |
| Ruina por varianza | Monte Carlo de probabilidad de ruina |
| Track record editable | Journal append-only con cadena de hashes SHA-256 |

Los criterios completos de candidatura (los 10 del charter) se evalúan por
combinación estrategia×vencimiento y aparecen como checklist en el informe;
si cualquiera falla, el veredicto es el negativo.

## Registro de experimentos

Cada ejecución de `research` queda registrada en SQLite
(`artifacts/experiments.sqlite`) con configuración completa, semilla,
veredicto y métricas por combinación — reproducible desde cero.

## Fuentes de leakage, supuestos y limitaciones

El informe generado (`artifacts/report.md` / `.html`) incluye una sección fija
con las posibles fuentes de leakage y su control, y otra con los supuestos del
simulador (ejecución al open tras latencia, payout independiente del flujo,
persistencia no garantizada de patrones OTC, etc.). Léelas antes de sacar
conclusiones de cualquier número.
