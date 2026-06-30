from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _find_latest_run(reports_dir: Path) -> Path | None:
    runs = sorted(reports_dir.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0] if runs else None


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _add_if_exists(zf: zipfile.ZipFile, root: Path, rel: str) -> None:
    p = root / rel
    if p.exists() and p.is_file():
        zf.write(p, arcname=rel)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", nargs="?", default=".", help="项目根目录（默认 . ）")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    latest_run = _find_latest_run(reports)
    out_zip = reports / "support_bundle_latest.zip"

    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "project_dir": str(root),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "latest_run": str(latest_run) if latest_run else None,
    }

    key_files = [
        "README.md",
        "REBUILD_NOTE_20260313.txt",
        "REBUILD_NOTE_20260314_CHATGPT.txt",
        "REBUILD_NOTE_20260314_SUPPORT_VERIFIED.txt",
        "REBUILD_NOTE_20260317_CHATGPT.txt",
        "VERIFICATION_SUMMARY_20260317.txt",
        "FIX_PERMISSIONS_README.txt",
        "config.yml",
        "requirements.txt",
        "run.sh",
        "make_upload_bundle.sh",
        "run_message_stack_backtest.sh",
        "run_branch_fast_research.sh",
        "run_send_files.sh",
        "run_stage84_aggressive_then_conservative.sh",
        "run_stage85_event_state_sprint.sh",
        "run_okx_demo_runner.sh",
        "start_okx_demo.sh",
        "pause_okx_demo.sh",
        "start_shortwave_demo.sh",
        "pause_shortwave_demo.sh",
        "start_branch_demo.sh",
        "pause_branch_demo.sh",
        "config_shortwave_candidate.yml.example",
        "shadow_shortwave_candidate.yml.example",
        "config_shortwave_candidate.yml",
        "shadow_shortwave_candidate.yml",
        "shadow.yml",
        "shadow.yml.example",
        ".okx_demo_env.example",
        "risk_override.yml",
        "risk_override.yml.example",
        "src/version.py",
        "src/main.py",
        "src/backtest/engine.py",
        "src/backtest/indicators.py",
        "src/backtest/io.py",
        "src/backtest/metrics.py",
        "src/live/binance_shadow.py",
        "src/live/okx_shadow.py",
        "tools/make_support_bundle.py",
        "tools/send_files_pack.py",
        "tools/build_branch_demo_candidate.py",
        "tools/apply_patch.py",
        "tools/build_current_strategy_trades.py",
        "tools/message_stack_backtest.py",
        "tools/finalize_research_outputs.py",
        "tools/alt_shortwave_lab.py",
        "tools/alt_shortwave_message_overlay.py",
        "tools/alt_shortwave_symbol_overlay.py",
        "tools/overfit_check.py",
        "tools/fetch_binance_funding.py",
        "tools/run_shadow.py",
        "tools/binance_testnet_probe.py",
        "tools/binance_testnet_smoke_submit.py",
        "tools/okx_demo_common.py",
        "tools/okx_demo_probe.py",
        "tools/okx_demo_smoke_submit.py",
        "tools/okx_demo_shadow_exec.py",
        "tools/okx_demo_runner.py",
        "tools/okx_demo_autopilot.py",
    ]

    fingerprints: dict[str, str] = {}
    for rel in key_files:
        p = root / rel
        if p.exists() and p.is_file():
            fingerprints[rel] = _sha256_file(p)

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bundle_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr("code_fingerprint.json", json.dumps(fingerprints, ensure_ascii=False, indent=2))

        for rel in key_files:
            _add_if_exists(zf, root, rel)

        run_metrics_bytes = None
        run_metrics = None
        if latest_run is not None:
            p_run_metrics = latest_run / "metrics.json"
            if p_run_metrics.exists() and p_run_metrics.is_file():
                run_metrics_bytes = p_run_metrics.read_bytes()
                try:
                    run_metrics = json.loads(run_metrics_bytes.decode("utf-8"))
                except Exception:
                    run_metrics = None

        if run_metrics_bytes is not None:
            zf.writestr("metrics_latest.json", run_metrics_bytes)
        else:
            _add_if_exists(zf, reports, "metrics_latest.json")

        extra_reports = [
            "deepseek_brief_latest.txt",
            "research_report_latest.txt",
            "message_stack_backtest_latest.txt",
            "current_demo_strategy_trades_latest.csv",
            "monthly_returns_latest.csv",
            "monthly_stats_latest.txt",
            "shadow_mode_plan_latest.json",
            "shadow_mode_plan_latest.md",
            "mainline_combo_validation_latest.txt",
            "branch_structure_lab_latest.txt",
            "shortwave_demo_report_latest.txt",
            "testnet_probe_latest.json",
            "testnet_probe_latest.jsonl",
            "testnet_probe_latest.txt",
            "testnet_smoke_submit_latest.json",
            "testnet_smoke_submit_latest.jsonl",
            "testnet_smoke_submit_latest.txt",
            "okx_demo_probe_latest.json",
            "okx_demo_probe_latest.jsonl",
            "okx_demo_probe_latest.txt",
            "okx_demo_smoke_submit_latest.json",
            "okx_demo_smoke_submit_latest.jsonl",
            "okx_demo_smoke_submit_latest.txt",
            "okx_demo_shadow_exec_latest.json",
            "okx_demo_shadow_exec_latest.jsonl",
            "okx_demo_shadow_exec_latest.txt",
            "okx_demo_checkin_latest.json",
            "okx_demo_checkin_latest.txt",
            "okx_demo_checkin_history.jsonl",
            "okx_demo_runner_status_latest.json",
        ]
        for rel in extra_reports:
            _add_if_exists(zf, reports, rel)
        research_raw = reports / "research_raw"
        if research_raw.exists() and research_raw.is_dir():
            for p in sorted(research_raw.glob("*")):
                if p.is_file():
                    zf.write(p, arcname=f"reports/research_raw/{p.name}")


        runtime_reports = [
            ".runtime/okx_demo_shadow_exec_latest.json",
            ".runtime/okx_demo_shadow_exec_latest.jsonl",
            ".runtime/okx_demo_shadow_exec_latest.txt",
            ".runtime/okx_demo_autopilot_state.json",
        ]
        for rel in runtime_reports:
            _add_if_exists(zf, root, rel)

        for downloads_name in ["okx_demo_report_latest.txt", "branch_demo_report_latest.txt", "deepseek_single_file_latest.txt"]:
            downloads_report = Path.home() / "Downloads" / downloads_name
            if downloads_report.exists() and downloads_report.is_file():
                zf.write(downloads_report, arcname=f"downloads/{downloads_name}")

        try:
            cfg_text = (root / "config.yml").read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*version:\s*(\S+)", cfg_text, flags=re.M)
            cfg_version = m.group(1) if m else None
        except Exception:
            cfg_version = None

        check = {
            "config_version": cfg_version,
            "latest_run": str(latest_run) if latest_run else None,
        }
        if isinstance(run_metrics, dict):
            check["run_metrics"] = run_metrics.get("metrics", {})
            check["snapshot"] = run_metrics.get("snapshot", {})
        zf.writestr("bundle_check.json", json.dumps(check, ensure_ascii=False, indent=2))

        if latest_run is not None:
            for fn in ["metrics.json", "equity_curve.csv", "trades.csv"]:
                p = latest_run / fn
                if p.exists():
                    zf.write(p, arcname=f"run_latest/{fn}")


if __name__ == "__main__":
    main()
