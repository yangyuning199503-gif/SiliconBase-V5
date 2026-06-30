from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


def _safe_relpath(p: str) -> str:
    p = p.replace("\\", "/")
    p = p.lstrip("/")
    if ".." in p.split("/"):
        raise ValueError(f"非法路径（包含 ..）：{p}")
    return p


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("patch_zip", help="补丁 zip 路径（通常在 ~/Downloads/）")
    ap.add_argument("target_dir", help="目标目录（推荐用 . ）")
    ap.add_argument("--dry-run", action="store_true", help="仅检查，不落盘")
    ap.add_argument("--allow-golden", action="store_true", help="允许覆盖 data/raw（不建议）")
    args = ap.parse_args()

    patch_zip = Path(args.patch_zip).expanduser()
    target_dir = Path(args.target_dir).expanduser()

    if not patch_zip.exists():
        raise SystemExit(f"补丁不存在：{patch_zip}")
    if not target_dir.exists():
        raise SystemExit(f"目标目录不存在：{target_dir}")

    with zipfile.ZipFile(patch_zip, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if "manifest.json" not in names:
            raise SystemExit("补丁缺少 manifest.json（必须包含）")

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if not isinstance(manifest, dict) or "files" not in manifest or not isinstance(manifest["files"], dict):
            raise SystemExit("manifest.json 格式错误：必须是 dict 且包含 files(dict)")

        files = list(manifest["files"].keys())
        # 基本校验：files 必须在 zip 内
        missing = [f for f in files if f not in names]
        if missing:
            raise SystemExit("补丁 zip 内缺少以下文件：\n" + "\n".join(missing))

        # 备份目录
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_root = Path.home() / ".patch_backups" / f"backup_{ts}"
        planned = []

        for rel in files:
            rel_safe = _safe_relpath(rel)
            if rel_safe.startswith("data/raw") and not args.allow_golden:
                raise SystemExit(f"禁止覆盖黄金数据：{rel_safe}（如确有需要，使用 --allow-golden）")

            content = zf.read(rel)
            # sha 校验（如 manifest 给了）
            want = manifest["files"].get(rel, {}).get("sha256")
            if want:
                got = _sha256_bytes(content)
                if got != want:
                    raise SystemExit(f"sha256 不匹配：{rel} | want={want} got={got}")

            dst = target_dir / rel_safe
            planned.append((rel, dst))

        print("补丁预览：")
        for rel, dst in planned:
            print(f"- {rel} -> {dst}")

        if args.dry_run:
            print("dry-run 完成：未写入任何文件。")
            return

        # 执行备份 + 覆盖
        for rel, dst in planned:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                bkp = backup_root / _safe_relpath(rel)
                bkp.parent.mkdir(parents=True, exist_ok=True)
                bkp.write_bytes(dst.read_bytes())

        for rel, dst in planned:
            dst.write_bytes(zf.read(rel))

        print(f"补丁已应用。备份目录：{backup_root}")

if __name__ == "__main__":
    main()
