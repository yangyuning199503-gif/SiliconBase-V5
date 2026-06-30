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


def _read_yaml(p: Path) -> dict[str, Any]:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _write_yaml(obj: dict[str, Any], p: Path) -> None:
    p.write_text(yaml.safe_dump(obj, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _run_one(py: str, cfg_path: Path, run_id: str) -> dict[str, Any]:
    cmd = [py, "-m", "src.main", "--config", str(cfg_path), "--run-id", run_id]
    subprocess.run(cmd, check=True)

    cfg = _read_yaml(cfg_path)
    reports_dir = Path(cfg.get("outputs", {}).get("reports_dir", "reports"))
    run_dir = reports_dir / f"run_{run_id}"

    metrics_blob = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    metrics = metrics_blob.get("metrics", {})
    snapshot = metrics_blob.get("snapshot", {}) or {}

    # last trade time
    last_trade = None
    trades_csv = run_dir / "trades.csv"
    if trades_csv.exists():
        try:
            tdf = pd.read_csv(trades_csv)
            if not tdf.empty and "exit_time" in tdf.columns:
                last_trade = str(pd.to_datetime(tdf["exit_time"]).max())
        except Exception:
            last_trade = None

    dd_guard_triggers = None
    if isinstance(snapshot, dict):
        dd_guard_triggers = (snapshot.get("dd_guard") or {}).get("triggers")

    return {
        "variant": cfg.get("system", {}).get("version", run_id),
        "symbols": ",".join(cfg.get("data", {}).get("symbols", [])),
        "total_return": float(metrics.get("total_return", 0.0)),
        "cagr": float(metrics.get("cagr", 0.0)),
        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "trades": int(metrics.get("trades", 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "dd_guard_triggers": dd_guard_triggers if dd_guard_triggers is not None else "",
        "last_trade": last_trade or "",
        "run_id": run_id,
        "run_dir": str(run_dir),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", default="config.yml", help="基准配置（默认 config.yml）")
    ap.add_argument("--python", default="./.venv/bin/python", help="Python 路径（默认 ./.venv/bin/python）")
    ap.add_argument(
        "--variants",
        default="btc_only,bnb_only,btc_bnb",
        help="要跑的组合：btc_only,bnb_only,btc_bnb（逗号分隔）",
    )
    args = ap.parse_args()

    base_cfg_path = Path(args.base_config)
    base = _read_yaml(base_cfg_path)
    reports_dir = Path(base.get("outputs", {}).get("reports_dir", "reports"))
    out_dir = reports_dir / "matrix"
    out_dir.mkdir(parents=True, exist_ok=True)

    base_ver = str(base.get("system", {}).get("version", "base"))
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    variants = [v.strip() for v in str(args.variants).split(",") if v.strip()]

    results: list[dict[str, Any]] = []

    for v in variants:
        cfg = copy.deepcopy(base)
        cfg.setdefault("system", {})
        cfg.setdefault("data", {})
        cfg["system"]["version"] = f"{base_ver}_{v}"

        if v == "btc_only":
            cfg["data"]["symbols"] = ["btc"]
            cfg["data"]["weights"] = "equal"
        elif v == "bnb_only":
            cfg["data"]["symbols"] = ["bnb"]
            cfg["data"]["weights"] = "equal"
        elif v == "btc_bnb":
            cfg["data"]["symbols"] = ["btc", "bnb"]
            cfg["data"]["weights"] = "equal"
        else:
            raise SystemExit(f"未知 variant：{v}")

        cfg_path = out_dir / f"config_{v}_{ts}.yml"
        _write_yaml(cfg, cfg_path)

        run_id = f"{ts}_{v}"
        print(f"\n=== RUN {v} | run_id={run_id} ===")
        res = _run_one(args.python, cfg_path, run_id)
        results.append(res)

    df = pd.DataFrame(results)
    if df.empty:
        raise SystemExit("无结果")

    # 排序：先 CAGR，再 PF
    df = df.sort_values(["cagr", "profit_factor"], ascending=[False, False])

    view = df[
        [
            "variant",
            "symbols",
            "total_return",
            "cagr",
            "max_drawdown",
            "profit_factor",
            "trades",
            "dd_guard_triggers",
            "last_trade",
        ]
    ].copy()

    # 格式化
    view["total_return"] = view["total_return"].map(lambda x: f"{x*100:.2f}%")
    view["cagr"] = view["cagr"].map(lambda x: f"{x*100:.2f}%")
    view["max_drawdown"] = view["max_drawdown"].map(lambda x: f"{x*100:.2f}%")
    view["profit_factor"] = view["profit_factor"].map(lambda x: f"{x:.2f}")
    view["trades"] = view["trades"].astype(int)

    txt = tabulate(view, headers="keys", tablefmt="github", showindex=False)

    out_txt = reports_dir / "matrix_summary_latest.txt"
    out_txt.write_text(txt + "\n", encoding="utf-8")

    out_csv = reports_dir / "matrix_summary_latest.csv"
    df.to_csv(out_csv, index=False)

    print("\n====== MATRIX SUMMARY ======")
    print(txt)
    print("============================\n")
    print(f"已写入：{out_txt}")
    print(f"已写入：{out_csv}")

    # 复制到 Downloads，方便直接上传/转发
    dl = Path.home() / "Downloads"
    if dl.exists():
        shutil.copy2(out_txt, dl / out_txt.name)
        shutil.copy2(out_csv, dl / out_csv.name)
        print(f"已复制到：{dl / out_txt.name}")
        print(f"已复制到：{dl / out_csv.name}")


if __name__ == "__main__":
    main()
