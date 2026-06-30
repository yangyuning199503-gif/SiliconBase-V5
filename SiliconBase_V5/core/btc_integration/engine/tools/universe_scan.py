from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from tabulate import tabulate

SEGMENTS: list[tuple[str, str, str]] = [
    ("ret_2020_2021", "2020-01-01", "2021-12-31 23:59:59"),
    ("ret_2022_2023", "2022-01-01", "2023-12-31 23:59:59"),
    ("ret_2024_2026", "2024-01-01", "2026-01-31 23:59:59"),
]


def _read_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _write_yaml(obj: dict[str, Any], p: Path) -> None:
    p.write_text(yaml.safe_dump(obj, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _segment_stats(equity_csv: Path, seg_start: str, seg_end: str) -> tuple[float | None, float | None]:
    if not equity_csv.exists():
        return None, None
    try:
        df = pd.read_csv(equity_csv)
    except Exception:
        return None, None
    if df.empty or "time" not in df.columns or "equity" not in df.columns:
        return None, None
    try:
        df["time"] = pd.to_datetime(df["time"])
    except Exception:
        return None, None
    df = df.sort_values("time")
    df["equity"] = pd.to_numeric(df["equity"], errors="coerce").ffill()
    df = df.dropna(subset=["equity"])
    if df.empty:
        return None, None

    s = pd.to_datetime(seg_start)
    e = pd.to_datetime(seg_end)
    seg = df[(df["time"] >= s) & (df["time"] <= e)].copy()
    if seg.empty:
        return None, None

    eq = seg["equity"].astype(float).reset_index(drop=True)
    if len(eq) < 2:
        return None, None

    total_ret = float(eq.iloc[-1] / eq.iloc[0] - 1.0)
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return total_ret, float(dd)


def _ensure_data(
    py: str,
    symbol: str,
    out_path: Path,
    start: str,
    end: str,
    market: str,
    interval: str,
) -> bool:
    """Return True if data exists or fetched successfully."""
    if out_path.exists() and out_path.stat().st_size > 0:
        return True

    # 尝试拉取数据（若该币种在指定 market 不支持，可能失败）
    binance_sym = f"{symbol.upper()}USDT"
    cmd = [
        py,
        "-m",
        "tools.fetch_binance_klines",
        "--symbol",
        binance_sym,
        "--market",
        market,
        "--interval",
        interval,
        "--start",
        start,
        "--end",
        end,
        "--out",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _run_one(py: str, cfg_path: Path, run_id: str) -> dict[str, Any]:
    cmd = [py, "-m", "src.main", "--config", str(cfg_path), "--run-id", run_id]
    subprocess.run(cmd, check=True)

    cfg = _read_yaml(cfg_path)
    reports_dir = Path(cfg.get("outputs", {}).get("reports_dir", "reports"))
    run_dir = reports_dir / f"run_{run_id}"

    metrics_blob = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics = metrics_blob.get("metrics", {})
    snapshot = metrics_blob.get("snapshot", {}) or {}

    last_trade = ""
    trades_csv = run_dir / "trades.csv"
    if trades_csv.exists():
        try:
            tdf = pd.read_csv(trades_csv)
            if not tdf.empty and "exit_time" in tdf.columns:
                last_trade = str(pd.to_datetime(tdf["exit_time"]).max())
        except Exception:
            last_trade = ""

    dd_guard_triggers = ""
    if isinstance(snapshot, dict):
        dd_guard_triggers = str((snapshot.get("dd_guard") or {}).get("triggers", ""))

    # segments from equity curve
    equity_csv = run_dir / "equity_curve.csv"
    seg_map: dict[str, Any] = {}
    for key, s, e in SEGMENTS:
        r, dd = _segment_stats(equity_csv, s, e)
        seg_map[key] = r
        seg_map[key.replace("ret_", "dd_")] = dd

    res: dict[str, Any] = {
        "variant": cfg.get("system", {}).get("version", run_id),
        "symbol": ",".join(cfg.get("data", {}).get("symbols", [])),
        "total_return": float(metrics.get("total_return", 0.0)),
        "cagr": float(metrics.get("cagr", 0.0)),
        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "trades": int(metrics.get("trades", 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "dd_guard_triggers": dd_guard_triggers,
        "last_trade": last_trade,
        "run_id": run_id,
        "run_dir": str(run_dir),
    }
    res.update(seg_map)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default="config.yml", help="基准配置（默认 config.yml）")
    ap.add_argument("--python", default="./.venv/bin/python", help="Python 路径（默认 ./.venv/bin/python）")
    ap.add_argument(
        "--symbols",
        default="eth,sol,ada,dot,atom,matic,ltc,xrp,doge",
        help="要扫描的标的（逗号分隔，小写，如 bnb,eth,sol）",
    )
    ap.add_argument("--fetch-missing", action="store_true", help="缺数据则自动下载（Binance, 15m）")
    ap.add_argument("--market", default="futures", choices=["futures", "spot"], help="下载数据市场：futures/spot")
    ap.add_argument("--interval", default="15m", help="K线周期（默认 15m）")
    args = ap.parse_args()

    base_cfg_path = Path(args.base_config)
    base = _read_yaml(base_cfg_path)

    base_ver = str(base.get("system", {}).get("version", "base"))
    reports_dir = Path(base.get("outputs", {}).get("reports_dir", "reports"))
    out_dir = reports_dir / "universe"
    out_dir.mkdir(parents=True, exist_ok=True)

    start = str(base.get("data", {}).get("start", "2020-01-01"))
    end = str(base.get("data", {}).get("end", "2026-01-31"))
    csv_tpl = str(base.get("data", {}).get("csv_template", "data/raw/{symbol}_15m.csv"))

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    symbols = [s.strip().lower() for s in str(args.symbols).split(",") if s.strip()]

    results: list[dict[str, Any]] = []

    for sym in symbols:
        # ensure data
        out_path = Path(csv_tpl.format(symbol=sym))
        if args.fetch_missing:
            ok = _ensure_data(args.python, sym, out_path, start, end, args.market, args.interval)
            if not ok:
                print(f"[SKIP] {sym}: 无法获取数据（可能该币种在 {args.market} 不支持，或时间范围过早）")
                continue
        else:
            if not out_path.exists():
                print(f"[SKIP] {sym}: 缺少数据文件 {out_path}（可加 --fetch-missing 自动下载）")
                continue

        cfg = copy.deepcopy(base)
        cfg.setdefault("system", {})
        cfg.setdefault("data", {})
        cfg["system"]["version"] = f"{base_ver}_{sym}_only"
        cfg["data"]["symbols"] = [sym]
        cfg["data"]["weights"] = "equal"

        cfg_path = out_dir / f"config_{sym}_{ts}.yml"
        _write_yaml(cfg, cfg_path)

        run_id = f"{ts}_{sym}"
        print(f"\n=== RUN {sym} | run_id={run_id} ===")
        res = _run_one(args.python, cfg_path, run_id)
        results.append(res)

    df = pd.DataFrame(results)
    if df.empty:
        raise SystemExit("无结果：请检查数据文件是否存在，或使用 --fetch-missing")

    # 排序：先 CAGR，再 PF
    df = df.sort_values(["cagr", "profit_factor"], ascending=[False, False])

    view_cols = [
        "symbol",
        "total_return",
        "cagr",
        "max_drawdown",
        "profit_factor",
        "trades",
        "dd_guard_triggers",
        "ret_2020_2021",
        "ret_2022_2023",
        "ret_2024_2026",
        "last_trade",
    ]
    view = df[view_cols].copy()

    def _pct(x: Any) -> str:
        try:
            if x is None or (isinstance(x, float) and pd.isna(x)):
                return ""
            return f"{float(x)*100:.2f}%"
        except Exception:
            return ""

    view["total_return"] = view["total_return"].map(_pct)
    view["cagr"] = view["cagr"].map(_pct)
    view["max_drawdown"] = view["max_drawdown"].map(_pct)
    view["profit_factor"] = view["profit_factor"].map(lambda x: f"{float(x):.2f}")
    view["ret_2020_2021"] = view["ret_2020_2021"].map(_pct)
    view["ret_2022_2023"] = view["ret_2022_2023"].map(_pct)
    view["ret_2024_2026"] = view["ret_2024_2026"].map(_pct)

    txt = tabulate(view, headers="keys", tablefmt="github", showindex=False)

    out_txt = reports_dir / "universe_scan_latest.txt"
    out_csv = reports_dir / "universe_scan_latest.csv"
    out_txt.write_text(txt + "\n", encoding="utf-8")
    df.to_csv(out_csv, index=False)

    print("\n====== UNIVERSE SCAN SUMMARY ======")
    print(txt)
    print("==================================\n")
    print(f"已写入：{out_txt}")
    print(f"已写入：{out_csv}")

    dl = Path.home() / "Downloads"
    if dl.exists():
        shutil.copy2(out_txt, dl / out_txt.name)
        shutil.copy2(out_csv, dl / out_csv.name)
        print(f"已复制到：{dl / out_txt.name}")
        print(f"已复制到：{dl / out_csv.name}")


if __name__ == "__main__":
    main()
