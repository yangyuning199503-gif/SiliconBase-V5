from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import yaml

DEFAULT_CONFIGS = ["config.yml", "config_shortwave_candidate.yml"]


def _read_last_nonempty_line(path: Path) -> str:
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size <= 0:
            return ""
        buf = b""
        pos = size
        while pos > 0:
            step = 8192 if pos >= 8192 else pos
            pos -= step
            f.seek(pos)
            chunk = f.read(step)
            buf = chunk + buf
            lines = buf.splitlines()
            if pos == 0:
                for raw in reversed(lines):
                    text = raw.decode("utf-8", errors="ignore").strip()
                    if text:
                        return text
                return ""
            if len(lines) >= 2:
                for raw in reversed(lines[1:]):
                    text = raw.decode("utf-8", errors="ignore").strip()
                    if text:
                        return text
                buf = lines[0]
        return ""


def _last_timestamp_from_csv(path: Path) -> pd.Timestamp:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    last_line = _read_last_nonempty_line(path)
    if not last_line:
        raise ValueError(f"空文件: {path}")
    first_col = last_line.split(",", 1)[0].strip()
    if not first_col or first_col.lower() == "time":
        raise ValueError(f"无法从末行读取时间: {path}")
    ts = pd.to_datetime(first_col, errors="raise")
    if isinstance(ts, pd.DatetimeIndex):
        ts = ts[0]
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None) if hasattr(ts, "tz_convert") else ts.tz_localize(None)
    return pd.Timestamp(ts)


def _config_paths(root: Path, configs: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for item in configs:
        p = Path(item).expanduser()
        if not p.is_absolute():
            p = root / p
        if p not in out:
            out.append(p)
    return out


def _latest_common_end(root: Path, payload: dict) -> tuple[pd.Timestamp, list[tuple[str, Path, pd.Timestamp]]]:
    data = payload.get("data") or {}
    symbols = list(data.get("symbols") or [])
    template = str(data.get("csv_template") or "data/raw/{symbol}_15m.csv")
    if not symbols:
        raise ValueError("data.symbols 为空")
    rows: list[tuple[str, Path, pd.Timestamp]] = []
    for symbol in symbols:
        rel = template.format(symbol=symbol)
        csv_path = Path(rel)
        if not csv_path.is_absolute():
            csv_path = root / csv_path
        ts = _last_timestamp_from_csv(csv_path)
        rows.append((str(symbol), csv_path, ts))
    common_end = min(ts for _, _, ts in rows)
    return common_end, rows


def _update_one(root: Path, cfg_path: Path, dry_run: bool = False) -> str | None:
    if not cfg_path.exists() or not cfg_path.is_file():
        return f"[SKIP] {cfg_path}: 不存在"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8", errors="ignore")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"配置格式异常: {cfg_path}")
    common_end, rows = _latest_common_end(root, payload)
    new_end = common_end.strftime("%Y-%m-%d")
    data = payload.setdefault("data", {})
    old_end = data.get("end")
    changed = str(old_end) != new_end
    data["end"] = new_end
    if changed and not dry_run:
        cfg_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    legs = " | ".join(f"{sym}={ts.strftime('%Y-%m-%d %H:%M:%S')}" for sym, _, ts in rows)
    action = "UPDATE" if changed else "KEEP"
    suffix = " (dry-run)" if dry_run else ""
    return f"[{action}] {cfg_path.name}: end {old_end} -> {new_end} | common_latest={common_end.strftime('%Y-%m-%d %H:%M:%S')}{suffix} | {legs}"


def main() -> None:
    ap = argparse.ArgumentParser(description="把回测 config 的 data.end 对齐到本地 raw 最新共同日期。")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--config", dest="configs", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.project_dir).expanduser().resolve()
    configs = args.configs or DEFAULT_CONFIGS
    targets = _config_paths(root, configs)

    failed = False
    for cfg_path in targets:
        try:
            msg = _update_one(root, cfg_path, dry_run=args.dry_run)
            if msg:
                print(msg)
        except Exception as exc:
            failed = True
            print(f"[ERR] {cfg_path}: {exc}")
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
