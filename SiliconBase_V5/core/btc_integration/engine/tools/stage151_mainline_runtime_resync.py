from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _copy_runtime_overlays(src: dict[str, Any], dst: dict[str, Any]) -> None:
    for key in ["live_bridge", "outputs", "shadow", "execution", "autopilot"]:
        if isinstance(src.get(key), dict):
            dst[key] = src[key]


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _remove_if_exists(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    try:
        path.unlink()
        return True
    except Exception:
        return False


def _main() -> None:
    ap = argparse.ArgumentParser(description="Stage151: resync mainline runtime report to recovered fix8 baseline.")
    ap.add_argument("--project-dir", default=".")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    if root.name != "btc_system_v1":
        cand = root / "btc_system_v1"
        if cand.exists():
            root = cand.resolve()

    cfg_path = root / "config.yml"
    good_cfg_path = root / "config_mainline_dynlev_fix8_lock18.yml"
    backup_path = root / "config_stage151_pre_resync_backup.yml"
    current_cfg = _read_yaml(cfg_path)
    good_cfg = _read_yaml(good_cfg_path)
    if not good_cfg:
        raise SystemExit("缺少 config_mainline_dynlev_fix8_lock18.yml，无法同步主线 runtime。")

    if cfg_path.exists() and not backup_path.exists():
        shutil.copy2(cfg_path, backup_path)

    resynced_cfg = json.loads(json.dumps(good_cfg))
    resynced_cfg.setdefault("system", {})
    resynced_cfg["system"]["version"] = "r258_main_demo_mainline_live_dynlev_fix8_lock18_stage151"
    resynced_cfg["system"]["note"] = (
        "Stage151：在保留 Stage150 主线恢复结论不变的前提下，修正 runtime/report 同步。"
        "当前 runtime 明确锚定 mainline_live_dynlev_fix8_lock18，并清掉旧 stage148 live_base 残留报告。"
    )
    _copy_runtime_overlays(current_cfg, resynced_cfg)
    _write_yaml(cfg_path, resynced_cfg)

    downloads_dir = root.parent / "Downloads"
    runtime_dir = root / ".runtime"
    reports_dir = root / "reports" / "research_raw"
    reports_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    cleared = []
    for rel in [
        runtime_dir / "okx_demo_shadow_exec_latest.json",
        runtime_dir / "okx_demo_shadow_exec_latest.jsonl",
        runtime_dir / "okx_demo_shadow_exec_latest.txt",
        root / "reports" / "shadow_mode_plan_latest.json",
        root / "reports" / "shadow_mode_plan_latest.md",
        downloads_dir / "okx_demo_report_latest.txt",
    ]:
        if _remove_if_exists(rel):
            cleared.append(str(rel))

    stage150_path = root / "reports" / "research_raw" / "stage150_livebase_guard_and_mainline_recover_latest.txt"
    stage150_text = _safe_text(stage150_path)

    out_txt = reports_dir / "stage151_mainline_runtime_resync_latest.txt"
    out_json = reports_dir / "stage151_mainline_runtime_resync_latest.json"
    out_zip = downloads_dir / "stage151_mainline_runtime_resync_latest.zip"

    lines = []
    lines.append("Stage151 mainline runtime resync")
    lines.append("结论：Stage150 的主线恢复结论保留；这版只修 runtime/report 同步，不再让旧 stage148 报告覆盖当前主线。")
    lines.append("")
    lines.append("=== 已执行动作 ===")
    lines.append(f"- 当前 runtime version: {resynced_cfg.get('system', {}).get('version', '-')}")
    lines.append(f"- 当前 runtime config: {cfg_path}")
    lines.append(f"- 备份: {backup_path}")
    lines.append(f"- 已清理 stale runtime/report 文件数: {len(cleared)}")
    for p in cleared:
        lines.append(f"  - {p}")
    if stage150_text:
        lines.append("")
        lines.append("=== Stage150 延续结论 ===")
        for raw in stage150_text.splitlines():
            raw = raw.rstrip()
            if raw.startswith("- 主线稳定基线:") or raw.startswith("- ETH 当前最强锚点:") or raw.startswith("- 分支 BTC:") or raw.startswith("- 分支 SOL:"):
                lines.append(raw)
    lines.append("")
    lines.append("=== 下一步 ===")
    lines.append("- 先 pause/start 主线 Demo。")
    lines.append("- 新报告会先用当前 config version，直到下一轮 15m shadow_exec 写回新结果。")

    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "ok": True,
        "project_dir": str(root),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_version": resynced_cfg.get("system", {}).get("version"),
        "config_path": str(cfg_path),
        "backup_path": str(backup_path),
        "cleared": cleared,
        "stage150_path": str(stage150_path) if stage150_path.exists() else "",
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in [out_txt, out_json, cfg_path]:
            if p.exists():
                zf.write(p, arcname=p.name)

    print(json.dumps({"ok": True, "out_zip": str(out_zip), "out_txt": str(out_txt)}, ensure_ascii=False))


if __name__ == "__main__":
    _main()
