#!/usr/bin/env python3
"""
Shadow信号提供者
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
复用 okx_demo_shadow_exec 的完整回测/信号计算逻辑，
但只取信号不下单，供 QuantTradingRunner 或 AI 使用。
"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.logger import logger


@dataclass
class QuantSignal:
    """量化信号"""
    symbol: str
    inst_id: str
    desired_side: str          # "long", "short", "flat"
    desired_side_num: int      # 1, -1, 0
    target_notional_usdt: float
    target_leverage: str
    target_margin_usdt: float
    action_plan: list[dict[str, Any]]
    current_position: dict[str, Any] | None
    sizing_info: dict[str, Any]
    risk_override: dict[str, Any]
    coinglass: dict[str, Any]
    execution_sizing: dict[str, Any]
    pnl_snapshot: dict[str, Any]
    report_ok: bool
    report_reason: str
    raw_report: dict[str, Any] = field(repr=False)


class ShadowSignalProvider:
    """
    Shadow信号提供者

    通过调用 okx_demo_shadow_exec（设 OKX_PRECHECK_NO_SUBMIT=1）
    复用其完整的回测引擎、动态分仓、风控逻辑，只取信号不下单。
    """

    def __init__(self, project_dir: str, user_id: str):
        self.project_dir = Path(project_dir).resolve()
        self.user_id = user_id
        self.runtime_dir = self.project_dir / ".runtime"

    async def generate_signal(self) -> dict[str, QuantSignal]:
        """
        生成量化信号

        Returns:
            Dict[str, QuantSignal]: symbol -> 信号
        """
        report = await self._run_shadow_exec()
        return self._parse_report(report)

    async def _run_shadow_exec(self) -> dict[str, Any]:
        """运行 shadow_exec（不下单模式）"""
        env = os.environ.copy()
        env["OKX_PRECHECK_NO_SUBMIT"] = "1"
        env["OKX_NO_SUBMIT_ORDERS"] = "1"

        engine_dir = self.project_dir / "core" / "btc_integration" / "engine"
        shadow_exec_path = engine_dir / "tools" / "okx_demo_shadow_exec.py"
        cmd = [
            sys.executable,
            str(shadow_exec_path),
            "--project-dir", str(engine_dir),
            "--confirm-demo",
        ]

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(self.project_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if proc.returncode != 0:
                logger.warning(f"[ShadowSignalProvider] shadow_exec stderr: {proc.stderr[:500]}")

            # 读取报告文件
            report_path = self.runtime_dir / "okx_demo_shadow_exec_latest.json"
            if report_path.exists():
                try:
                    def _read_report():
                        with open(report_path, encoding='utf-8') as f:
                            return json.load(f)
                    return await asyncio.to_thread(_read_report)
                except Exception as e:
                    logger.error(f"[ShadowSignalProvider] 解析报告失败: {e}")

            # 尝试从 stdout 解析
            try:
                stdout_json = json.loads(proc.stdout.strip().splitlines()[-1])
                if isinstance(stdout_json, dict) and "ok" in stdout_json:
                    return stdout_json
            except Exception:
                pass

            return {"ok": False, "reason": "no_report_generated"}

        except subprocess.TimeoutExpired:
            logger.error("[ShadowSignalProvider] shadow_exec 超时")
            return {"ok": False, "reason": "timeout"}
        except Exception as e:
            logger.error(f"[ShadowSignalProvider] 运行 shadow_exec 失败: {e}")
            return {"ok": False, "reason": str(e)}

    def _parse_report(self, report: dict[str, Any]) -> dict[str, QuantSignal]:
        """解析 shadow_exec 报告为结构化信号"""
        signals: dict[str, QuantSignal] = {}

        if not isinstance(report, dict):
            return signals

        symbols_data = report.get("symbols", {})
        pnl_snapshot = report.get("pnl_snapshot", {})
        execution_sizing = report.get("execution_sizing", {})
        risk_override = report.get("risk_override", {})
        coinglass = report.get("coinglass", {})

        for sym_l, item in symbols_data.items():
            if not isinstance(item, dict):
                continue

            desired = item.get("desired_signal", {})
            current = item.get("current_position", {})
            action_plan = item.get("action_plan", [])

            signal = QuantSignal(
                symbol=str(sym_l).upper(),
                inst_id=item.get("inst_id", f"{sym_l.upper()}-USDT-SWAP"),
                desired_side=str(desired.get("side", "FLAT")).lower(),
                desired_side_num=int(desired.get("side_num", 0) or 0),
                target_notional_usdt=float(item.get("target_notional_usdt", 0) or 0),
                target_leverage=str(item.get("target_leverage", "1")),
                target_margin_usdt=float(item.get("target_margin_usdt", 0) or 0),
                action_plan=action_plan if isinstance(action_plan, list) else [],
                current_position=current if isinstance(current, dict) else None,
                sizing_info=item.get("sizing", {}),
                risk_override=risk_override if isinstance(risk_override, dict) else {},
                coinglass=coinglass if isinstance(coinglass, dict) else {},
                execution_sizing=execution_sizing if isinstance(execution_sizing, dict) else {},
                pnl_snapshot=pnl_snapshot if isinstance(pnl_snapshot, dict) else {},
                report_ok=bool(report.get("ok")),
                report_reason=str(report.get("reason", "")),
                raw_report=item,
            )
            signals[sym_l] = signal

        return signals
