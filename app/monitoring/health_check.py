from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.data.polymarket_gamma import get_active_events
from app.execution.paper_report import build_performance_report
from app.risk.paper_limits import load_paper_risk_state
from app.monitoring.supervisor_journal import load_supervisor_journal


DATA_DIR = Path("data")

REQUIRED_RUNTIME_FILES = [
    DATA_DIR / "paper_trades.csv",
    DATA_DIR / "orderbook_history.csv",
    DATA_DIR / "paper_performance_report.csv",
    DATA_DIR / "supervisor_journal.csv",
]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_item(name: str, status: str, detail: str) -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
    }


def summarize_overall_status(checks: list[dict[str, str]]) -> str:
    statuses = {check.get("status", "UNKNOWN") for check in checks}

    if "FAIL" in statuses:
        return "FAIL"

    if "WARN" in statuses:
        return "WARN"

    return "OK"


def run_health_check(
    max_journal_age_minutes: float = 30.0,
    min_orderbook_rows: int = 1,
    max_open_positions: int = 3,
    max_total_exposure_usdc: float = 15.0,
    skip_api: bool = False,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    for path in REQUIRED_RUNTIME_FILES:
        if path.exists():
            checks.append(
                check_item(
                    f"runtime file: {path}",
                    "OK",
                    "Existe.",
                )
            )
        else:
            checks.append(
                check_item(
                    f"runtime file: {path}",
                    "WARN",
                    "No existe todavía o fue limpiado. Puede ser normal si el bot no ha generado ese archivo.",
                )
            )

    if skip_api:
        checks.append(
            check_item(
                "polymarket gamma api",
                "WARN",
                "Chequeo de API omitido por --skip-api.",
            )
        )
    else:
        try:
            events = get_active_events(limit=1)

            if events:
                checks.append(
                    check_item(
                        "polymarket gamma api",
                        "OK",
                        f"API respondió con {len(events)} evento(s).",
                    )
                )
            else:
                checks.append(
                    check_item(
                        "polymarket gamma api",
                        "WARN",
                        "API respondió, pero no devolvió eventos.",
                    )
                )
        except Exception as exc:
            checks.append(
                check_item(
                    "polymarket gamma api",
                    "FAIL",
                    f"No se pudo consultar API: {exc}",
                )
            )

    journal_rows = load_supervisor_journal(tail=1)

    if not journal_rows:
        checks.append(
            check_item(
                "supervisor journal latest",
                "FAIL",
                "No hay entradas en supervisor_journal.csv.",
            )
        )
    else:
        latest = journal_rows[-1]

        latest_status = str(latest.get("status", "")).upper()
        orderbook_rows = safe_int(latest.get("orderbook_rows_scanned"))

        observed_at_raw = str(latest.get("observed_at", ""))
        observed_at = parse_datetime(observed_at_raw)

        if observed_at is None:
            checks.append(
                check_item(
                    "journal timestamp",
                    "WARN",
                    f"No se pudo interpretar observed_at={observed_at_raw!r}.",
                )
            )
        else:
            now = datetime.now(timezone.utc)
            age_minutes = (now - observed_at.astimezone(timezone.utc)).total_seconds() / 60

            if age_minutes <= max_journal_age_minutes:
                checks.append(
                    check_item(
                        "journal freshness",
                        "OK",
                        f"Última entrada hace {round(age_minutes, 2)} min.",
                    )
                )
            else:
                checks.append(
                    check_item(
                        "journal freshness",
                        "WARN",
                        f"Última entrada hace {round(age_minutes, 2)} min; límite {max_journal_age_minutes} min.",
                    )
                )

        if latest_status == "OK":
            checks.append(
                check_item(
                    "latest supervisor status",
                    "OK",
                    "Último ciclo terminó en OK.",
                )
            )
        elif latest_status:
            checks.append(
                check_item(
                    "latest supervisor status",
                    "WARN",
                    f"Último ciclo terminó en {latest_status}.",
                )
            )
        else:
            checks.append(
                check_item(
                    "latest supervisor status",
                    "WARN",
                    "Último ciclo no tiene status.",
                )
            )

        if orderbook_rows >= min_orderbook_rows:
            checks.append(
                check_item(
                    "latest orderbook rows",
                    "OK",
                    f"Último ciclo escaneó {orderbook_rows} fila(s).",
                )
            )
        else:
            checks.append(
                check_item(
                    "latest orderbook rows",
                    "FAIL",
                    f"Último ciclo escaneó {orderbook_rows} fila(s); mínimo {min_orderbook_rows}.",
                )
            )

    try:
        risk_state = load_paper_risk_state()

        if risk_state.open_positions <= max_open_positions:
            checks.append(
                check_item(
                    "open position limit",
                    "OK",
                    f"{risk_state.open_positions}/{max_open_positions} posiciones abiertas.",
                )
            )
        else:
            checks.append(
                check_item(
                    "open position limit",
                    "FAIL",
                    f"{risk_state.open_positions}/{max_open_positions} posiciones abiertas.",
                )
            )

        if risk_state.open_exposure_usdc <= max_total_exposure_usdc:
            checks.append(
                check_item(
                    "open exposure limit",
                    "OK",
                    f"${risk_state.open_exposure_usdc}/${max_total_exposure_usdc} expuesto.",
                )
            )
        else:
            checks.append(
                check_item(
                    "open exposure limit",
                    "FAIL",
                    f"${risk_state.open_exposure_usdc}/${max_total_exposure_usdc} expuesto.",
                )
            )
    except Exception as exc:
        checks.append(
            check_item(
                "paper risk state",
                "FAIL",
                f"No se pudo cargar estado de riesgo: {exc}",
            )
        )

    try:
        report = build_performance_report()

        checks.append(
            check_item(
                "paper report",
                "OK",
                (
                    f"Reporte construido. "
                    f"PnL total PAPER=${report.get('total_paper_pnl_usdc', 0)}, "
                    f"ROI={report.get('total_paper_roi_pct', 0)}%."
                ),
            )
        )
    except Exception as exc:
        checks.append(
            check_item(
                "paper report",
                "FAIL",
                f"No se pudo construir reporte PAPER: {exc}",
            )
        )

    return {
        "overall_status": summarize_overall_status(checks),
        "checks": checks,
    }
