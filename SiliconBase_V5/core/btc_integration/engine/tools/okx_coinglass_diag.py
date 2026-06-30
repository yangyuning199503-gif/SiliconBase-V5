from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests
import yaml
from tools.okx_demo_common import ensure_env_loaded, load_credentials, now_utc_text, rest_request


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        obj = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _shadow_cfg(root: Path) -> dict[str, Any]:
    path = root / "shadow.yml"
    loaded = _read_yaml(path)
    obj = loaded.get("shadow", loaded) if isinstance(loaded, dict) else {}
    return obj if isinstance(obj, dict) else {}


def _coinglass_get(session: requests.Session, base_url: str, path: str, api_key: str, timeout: int = 18) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    out: dict[str, Any] = {"ok": False, "url": url, "path": path}
    try:
        resp = session.get(url, headers={"accept": "application/json", "CG-API-KEY": api_key}, timeout=timeout)
        out["status_code"] = resp.status_code
        out["ok"] = resp.status_code == 200
        try:
            out["data"] = resp.json()
        except Exception:
            out["data"] = {"raw": resp.text[:4000]}
    except Exception as e:
        out["error"] = str(e)
    return out


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ["data", "list", "rows", "items", "result"]:
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for key2 in ["list", "rows", "items"]:
                    val2 = val.get(key2)
                    if isinstance(val2, list):
                        return val2
    return []


def _extract_title(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj)
    for key in ["title", "headline", "name", "event", "eventName", "articleTitle"]:
        val = obj.get(key)
        if val:
            return str(val)
    return json.dumps(obj, ensure_ascii=False)[:180]


def _looks_like_noise_title(title: str) -> bool:
    s = str(title or "").strip().lower()
    if not s:
        return False
    return s.startswith("http://") or s.startswith("https://") or any(ext in s for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"])


def _summarize_okx(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    auth_cfg = cfg.get("auth", {}) if isinstance(cfg.get("auth"), dict) else {}
    env_load = ensure_env_loaded(root=root)
    creds, envs = load_credentials(auth_cfg if isinstance(auth_cfg, dict) else {}, root=root)
    out: dict[str, Any] = {
        "env": {**env_load, **envs},
        "credential_present": creds is not None,
        "account_config": {"ok": False},
    }
    if creds is None:
        out["reason"] = "missing_credentials"
        return out
    endpoints = cfg.get("endpoints", {}) if isinstance(cfg.get("endpoints"), dict) else {}
    rest_base = str(endpoints.get("rest_base", "https://www.okx.com"))
    session = requests.Session()
    st, data, meta = rest_request(session, "GET", rest_base, "/api/v5/account/config", creds=creds, signed=True, demo=True)
    code = data.get("code") if isinstance(data, dict) else None
    msg = data.get("msg") if isinstance(data, dict) else None
    row = None
    if isinstance(data, dict) and isinstance(data.get("data"), list) and data.get("data"):
        row0 = data["data"][0]
        if isinstance(row0, dict):
            row = {
                "uid": row0.get("uid"),
                "posMode": row0.get("posMode"),
                "acctLv": row0.get("acctLv"),
            }
    out["account_config"] = {
        "ok": st == 200 and str(code) == "0",
        "status_code": st,
        "code": code,
        "msg": msg,
        "meta": meta,
        "row": row,
    }
    if not out["account_config"]["ok"]:
        out["reason"] = "account_config_failed"
    else:
        out["reason"] = "ok"
    return out


def _summarize_coinglass(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    ensure_env_loaded(root=root)
    api_key = os.environ.get("COINGLASS_API_KEY", "").strip()
    cg_cfg = (((cfg.get("autopilot") or {}) if isinstance(cfg.get("autopilot"), dict) else {}).get("coinglass") or {})
    if not isinstance(cg_cfg, dict):
        cg_cfg = {}
    enabled = bool(cg_cfg.get("enabled", True))
    base_url = str(cg_cfg.get("base_url", "https://open-api-v4.coinglass.com"))
    news_path = str(cg_cfg.get("news_path", "/api/article/list"))
    economic_path = str(cg_cfg.get("economic_path", "/api/calendar/economic-data"))
    out: dict[str, Any] = {
        "enabled": enabled,
        "api_key_present": bool(api_key),
        "news": {"ok": False},
        "economic": {"ok": False},
    }
    if not enabled:
        out["reason"] = "coinglass_disabled"
        return out
    if not api_key:
        out["reason"] = "missing_COINGLASS_API_KEY"
        return out
    session = requests.Session()
    news = _coinglass_get(session, base_url, news_path, api_key)
    news_items = _extract_items(news.get("data"))
    news_title = _extract_title(news_items[0]) if news_items else ""
    out["news"] = {
        "ok": bool(news.get("ok")),
        "status_code": news.get("status_code"),
        "sample_title": news_title,
        "sample_title_is_noise_url": _looks_like_noise_title(news_title),
        "count_hint": len(news_items),
        "error": news.get("error"),
    }
    econ = _coinglass_get(session, base_url, economic_path, api_key)
    econ_items = _extract_items(econ.get("data"))
    econ_title = _extract_title(econ_items[0]) if econ_items else ""
    out["economic"] = {
        "ok": bool(econ.get("ok")),
        "status_code": econ.get("status_code"),
        "sample_title": econ_title,
        "count_hint": len(econ_items),
        "error": econ.get("error"),
    }
    out["reason"] = "ok" if out["news"]["ok"] and out["economic"]["ok"] else "coinglass_request_failed"
    return out


def _write_txt(path: Path, report: dict[str, Any]) -> None:
    okx = report.get("okx", {}) if isinstance(report.get("okx"), dict) else {}
    cg = report.get("coinglass", {}) if isinstance(report.get("coinglass"), dict) else {}
    lines = [
        f"ts_utc: {report.get('ts_utc', '')}",
        f"project_dir: {report.get('project_dir', '')}",
        f"okx_credential_present: {okx.get('credential_present', False)}",
        f"okx_reason: {okx.get('reason', '')}",
        f"okx_account_config_ok: {((okx.get('account_config') or {}).get('ok', False) if isinstance(okx.get('account_config'), dict) else False)}",
        f"okx_account_config_status_code: {((okx.get('account_config') or {}).get('status_code', '') if isinstance(okx.get('account_config'), dict) else '')}",
        f"okx_account_config_code: {((okx.get('account_config') or {}).get('code', '') if isinstance(okx.get('account_config'), dict) else '')}",
        f"coinglass_api_key_present: {cg.get('api_key_present', False)}",
        f"coinglass_reason: {cg.get('reason', '')}",
        f"coinglass_news_ok: {((cg.get('news') or {}).get('ok', False) if isinstance(cg.get('news'), dict) else False)}",
        f"coinglass_news_status_code: {((cg.get('news') or {}).get('status_code', '') if isinstance(cg.get('news'), dict) else '')}",
        f"coinglass_news_sample_title: {((cg.get('news') or {}).get('sample_title', '') if isinstance(cg.get('news'), dict) else '')}",
        f"coinglass_news_sample_title_is_noise_url: {((cg.get('news') or {}).get('sample_title_is_noise_url', False) if isinstance(cg.get('news'), dict) else False)}",
        f"coinglass_economic_ok: {((cg.get('economic') or {}).get('ok', False) if isinstance(cg.get('economic'), dict) else False)}",
        f"coinglass_economic_status_code: {((cg.get('economic') or {}).get('status_code', '') if isinstance(cg.get('economic'), dict) else '')}",
        f"coinglass_economic_sample_title: {((cg.get('economic') or {}).get('sample_title', '') if isinstance(cg.get('economic'), dict) else '')}",
    ]
    env = okx.get("env", {}) if isinstance(okx.get("env"), dict) else {}
    checked = env.get("env_files_checked", []) if isinstance(env.get("env_files_checked"), list) else []
    loaded = env.get("env_files_loaded", []) if isinstance(env.get("env_files_loaded"), list) else []
    lines.append(f"env_files_checked: {' | '.join(str(x) for x in checked)}")
    lines.append(f"env_files_loaded: {' | '.join(str(x) for x in loaded)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate OKX Demo and CoinGlass credential wiring")
    ap.add_argument("--project-dir", default=".")
    ap.add_argument("--out-json", default="reports/okx_coinglass_diag_latest.json")
    ap.add_argument("--out-txt", default="reports/okx_coinglass_diag_latest.txt")
    args = ap.parse_args()

    root = Path(args.project_dir).resolve()
    shadow_cfg = _shadow_cfg(root)
    autopilot_cfg = ((shadow_cfg.get("autopilot") or {}) if isinstance(shadow_cfg.get("autopilot"), dict) else {})

    report: dict[str, Any] = {
        "ts_utc": now_utc_text(),
        "project_dir": str(root),
        "okx": _summarize_okx(root, shadow_cfg),
        "coinglass": _summarize_coinglass(root, autopilot_cfg),
    }

    out_json = root / args.out_json
    out_txt = root / args.out_txt
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_txt(out_txt, report)
    print(json.dumps({
        "ok": bool(((report.get("okx") or {}).get("account_config") or {}).get("ok")) and bool(((report.get("coinglass") or {}).get("news") or {}).get("ok")) and bool(((report.get("coinglass") or {}).get("economic") or {}).get("ok")),
        "out_json": str(out_json),
        "out_txt": str(out_txt),
        "okx_reason": (report.get("okx") or {}).get("reason"),
        "coinglass_reason": (report.get("coinglass") or {}).get("reason"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
