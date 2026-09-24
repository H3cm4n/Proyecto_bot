#!/bin/bash

# Limpiar variable TMUX para permitir ejecución fluida
unset TMUX

SESSION="polymarket_bot"

tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
    echo "[INFO] Conectando a la sesión de Tmux existente: $SESSION"
    tmux attach-session -t $SESSION
    exit 0
fi

# 1. Panel Principal (Izquierda): Bot de trading en tiempo real
tmux new-session -d -s $SESSION -n "Dashboard" "python3 tools/directional_limit_hunter_executor.py --live"

# 2. Panel Derecho: Gráfico ASCII de precios Spot en tiempo real
tmux split-window -h -t $SESSION "python3 tools/ascii_chart.py"

# 3. Panel Inferior: Monitor dinámico del portafolio en JSON
tmux split-window -v -t $SESSION:0.0 "watch -n 1 'cat paper_portfolio.json | grep -E \"(balance_usd|symbol|size|status|avg_price)\"'"

# Ajustar distribución proporcional del diseño
tmux resize-pane -t $SESSION:0.0 -y 70%

# Conectar a la sesión interactiva
tmux attach-session -t $SESSION
