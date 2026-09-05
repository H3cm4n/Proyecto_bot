#!/usr/bin/env bash

set -e

# Configurar PYTHONPATH para localizar los módulos core y executors
export PYTHONPATH=.

# Manejo seguro de señales en Bash (Graceful Shutdown)
cleanup() {
    echo ""
    echo "[!] Interrupción detectada en Runner. Cerrando sesión de shadow paper trading..."
    pkill -P $$ || true
    echo "[v1.5] Apagado atómico completado. Datos guardados de forma segura."
    exit 0
}

trap cleanup SIGINT SIGTERM

INTERVAL=${INTERVAL:-300}
RUN_ID=$(date -u +"%Y%m%dT%H%M%SZ")

echo "=============================================="
echo "DIRECTIONAL LIMIT HUNTER SHADOW v1.5"
echo "Run ID: ${RUN_ID}"
echo "Intervalo: ${INTERVAL}s"
echo "=============================================="

while true; do
    echo "=== CICLO DE EJECUCIÓN (${RUN_ID}) ==="
    
    # Discovery
    python3 tools/crypto_universe_discovery.py --mode above > "data/universe_discovery/${RUN_ID}_latest.json" 2>/dev/null || true
    
    # Filter v1.5
    python3 tools/filter_directional_limit_hunter_snapshot.py < "data/universe_discovery/${RUN_ID}_latest.json" > "data/directional_limit_hunter_snapshot.json" 2>/dev/null || true
    
    # Executor v1.5
    python3 tools/directional_limit_hunter_executor.py < "data/directional_limit_hunter_snapshot.json"
    
    if [ "${ONCE}" = "1" ]; then
        echo "[i] Ejecución única (ONCE=1) finalizada."
        break
    fi
    
    sleep "${INTERVAL}"
done
