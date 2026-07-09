# Polymarket AI Bot

Bot experimental para analizar mercados de Polymarket en modo seguro.

## Estado actual

El bot funciona en modo **READ-ONLY** y **PAPER-TRADING**.

No usa wallet.
No usa private key.
No ejecuta compras reales.
No vende posiciones reales.

## Funciones actuales

- Lee eventos activos de Polymarket.
- Consulta orderbooks públicos.
- Calcula bid, ask, spread, mid price y liquidez.
- Genera score de señales.
- Penaliza spreads relativos altos.
- Simula compras paper.
- Evita comprar ambos lados del mismo mercado.
- Valúa posiciones abiertas.
- Cierra posiciones paper por stop-loss o take-profit.
- Genera reporte de performance.

## Comandos principales

```bash
python main.py snapshot
python main.py snapshot --alerts --min-score 50
python main.py snapshot --alerts --min-score 50 --paper --paper-size 5 --paper-min-score 75

python main.py scan --cycles 2 --interval 10 --alerts --min-score 65
python main.py portfolio
python main.py paper-manage
python main.py paper-manage --close
python main.py paper-report
## Seguridad

Este proyecto todavía no debe usarse con dinero real.

LIVE_TRADING debe permanecer en false.
