#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

mkdir -p data/raw

ensure_rw_dir() {
  local d="$1"
  if [ -e "$d" ] && [ ! -d "$d" ]; then
    rm -f "$d"
  fi
  mkdir -p "$d"
  chmod u+rwx "$d" 2>/dev/null || true
}

ensure_rw_dir reports
ensure_rw_dir logs

PY="./.venv/bin/python"

bootstrap_venv() {
  echo "Creating virtualenv .venv ..."
  rm -rf .venv
  python3 -m venv .venv
  PY="./.venv/bin/python"
  "$PY" -m pip install --upgrade pip >/dev/null
}

if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
  bootstrap_venv
fi

MARKER=".venv/.deps_installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  "$PY" -m pip install -r requirements.txt >/dev/null
  touch "$MARKER"
fi

"$PY" -m tools.align_backtest_end --project-dir . --config config.yml

"$PY" -m tools.repair_raw_from_snapshots --project-dir . --config config.yml >/dev/null || true

if ! "$PY" -m tools.raw_data_guard --project-dir . --config config.yml; then
  echo ""
  echo "STOP: 主线 raw 数据未通过连续性检查。先执行: bash refresh_mainline_raw.sh"
  echo "然后再执行: bash run.sh"
  exit 2
fi

"$PY" -m py_compile   src/main.py   src/backtest/engine.py   src/backtest/indicators.py   src/live/binance_shadow.py   src/live/okx_shadow.py   src/version.py   tools/make_support_bundle.py   tools/binance_testnet_probe.py   tools/okx_demo_common.py   tools/okx_demo_probe.py   tools/okx_demo_smoke_submit.py   tools/okx_demo_shadow_exec.py   tools/okx_demo_runner.py   tools/okx_demo_autopilot.py

echo "Running backtest ..."
RUN_ID="$(date +%Y%m%d_%H%M%S)"
"$PY" -m src.main --config config.yml --run-id "$RUN_ID"

echo "Building support bundle ..."
"$PY" -m tools.make_support_bundle .

"$PY" - <<'PY_SUMMARY'
import json
from pathlib import Path
import numpy as np

def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

def _pct(x: float) -> str:
    return f"{x*100:.2f}%"

def _find_metrics_path():
    candidates = [Path("reports/run_latest/metrics.json"), Path("reports/metrics_latest.json")]
    for c in candidates:
        if c.exists():
            return c
    runs = sorted(Path("reports").glob("run_*/metrics.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None

mp = _find_metrics_path()
if mp and mp.exists():
    payload = _read_json(mp) or {}
    m = payload.get("metrics", payload.get("run_metrics", {})) or {}
    snapshot = payload.get("snapshot", {}) or {}
    total_ret = float(m.get("total_return", 0.0))
    cagr = float(m.get("cagr", 0.0))
    maxdd = float(m.get("max_drawdown", 0.0))
    pf = float(m.get("profit_factor", 0.0))
    trades = int(m.get("trades", 0))
    win = float(m.get("win_rate", 0.0))
    sharpe = float(m.get("sharpe_daily", 0.0))
    dd_s = str(m.get("max_drawdown_start", "") or "")
    dd_e = str(m.get("max_drawdown_end", "") or "")
    print("")
    print("===== BACKTEST SUMMARY (ALL) =====")
    print(f"TotalRet: {_pct(total_ret)} | CAGR: {_pct(cagr)} | MaxDD: {_pct(maxdd)} | PF: {pf:.2f}")
    print(f"Trades: {trades} | WinRate: {_pct(win)} | Sharpe(daily): {sharpe:.2f}")
    if dd_s and dd_e:
        print(f"MaxDD Window: {dd_s} -> {dd_e}")
    funding = snapshot.get("funding", {}) if isinstance(snapshot, dict) else {}
    if isinstance(funding, dict) and funding.get("enabled"):
        print(f"FundingNetCost: {float(funding.get('net_cost_total', 0.0)):+.2f}")
    print("==================================")
    print("")
else:
    print("metrics.json not found under reports/")

mrp = Path("reports/monthly_returns_latest.csv")
if not mrp.exists():
    runs = sorted(Path("reports").glob("run_*/monthly_returns.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if runs:
        mrp = runs[0]

if mrp.exists():
    import pandas as pd
    df = pd.read_csv(mrp)
    if "return" in df.columns and len(df) > 0:
        r = df["return"].astype(float).to_numpy()
        mean = float(np.mean(r))
        p90 = float(np.quantile(r, 0.90))
        p95 = float(np.quantile(r, 0.95))
        mx = float(np.max(r))
        ge20 = int(np.sum(r >= 0.20))
        ge30 = int(np.sum(r >= 0.30))
        cum = float(np.prod(1.0 + r) - 1.0)
        print("===== MONTHLY DISTRIBUTION (ALL) =====")
        print(f"Mean: {_pct(mean)} | P90: {_pct(p90)} | P95: {_pct(p95)} | Max: {_pct(mx)} | >=20%: {ge20} | >=30%: {ge30} | Cum: {_pct(cum)}")
        print("======================================")
        print("")
        recent_n = 24 if len(r) >= 24 else len(r)
        if recent_n > 0:
            rr = r[-recent_n:]
            rmean = float(np.mean(rr))
            rp90 = float(np.quantile(rr, 0.90)) if len(rr) >= 2 else float(rr[0])
            rp95 = float(np.quantile(rr, 0.95)) if len(rr) >= 2 else float(rr[0])
            rmx = float(np.max(rr))
            rge20 = int(np.sum(rr >= 0.20))
            rge30 = int(np.sum(rr >= 0.30))
            rcum = float(np.prod(1.0 + rr) - 1.0)
            rcmgr = float((1.0 + rcum) ** (1.0 / recent_n) - 1.0)
            rann = float((1.0 + rcmgr) ** 12 - 1.0)
            print(f"===== MONTHLY DISTRIBUTION (RECENT {recent_n}M) =====")
            print(f"Mean: {_pct(rmean)} | P90: {_pct(rp90)} | P95: {_pct(rp95)} | Max: {_pct(rmx)} | >=20%: {rge20} | >=30%: {rge30} | Cum: {_pct(rcum)}")
            print(f"CompMonth: {_pct(rcmgr)} | CompAnn: {_pct(rann)}")
            print("===============================================")
            print("")
PY_SUMMARY

"$PY" -m tools.backtest_dual_window_report --project-dir . --recent-months 24 >/dev/null

"$PY" -m tools.send_files_pack --project-dir . --cleanup-downloads >/dev/null || true
echo "RAW: reports/research_raw/stage77_mainline_dual_window_latest.txt"
echo "PUBLIC: $HOME/Downloads/okx_demo_report_latest.txt"
echo "PUBLIC: $HOME/Downloads/deepseek_single_file_latest.txt"
echo "PUBLIC: $HOME/Downloads/chatgpt_bundle_latest.zip"
echo "Done. Outputs under: reports/"
