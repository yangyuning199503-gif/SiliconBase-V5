from __future__ import annotations

import argparse
import importlib.util
import json
from math import ceil
from pathlib import Path

import pandas as pd

SOL_SYMBOL = "sol"
BASE_ENTRY_TF = "5m"
BASE_FILTER_TF = "15m"
BASE_FAMILY = "bb_meanrev"
PARAM_IDS = ["p3", "p4"]
MODES = ["dual", "long_only", "short_only"]
STOP_PROFILES = [
    {"label": "base", "stop_scale": 1.00, "trail_scale": 1.00},
    {"label": "tight", "stop_scale": 0.92, "trail_scale": 0.92},
]
GATE_VARIANTS = [
    {"variant": "gate_range", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 1},
    {"variant": "gate_range", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 2},
    {"variant": "gate_range", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 3},
    {"variant": "gate_vote1_micro", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 1},
    {"variant": "gate_vote1_micro", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 2},
    {"variant": "gate_vote1_micro", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 3},
]
REFERENCE_CONTROLS = [
    {
        "control_id": "sol_highwin_reference",
        "symbol": "sol",
        "entry_tf": "1h",
        "filter_tf": "4h",
        "family": "bb_meanrev",
        "param_id": "p1",
        "mode": "long_only",
        "stop_profile": "base",
    },
]


def load_stage231_module(root: Path):
    stage231_path = root / "tools" / "stage231_seeded_confirmation_matrix.py"
    if not stage231_path.exists():
        raise FileNotFoundError(
            f"missing dependency: {stage231_path} | 先确认 stage231 patch 已经解压到当前系统目录"
        )
    spec = importlib.util.spec_from_file_location("stage231_seeded_confirmation_matrix", stage231_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {stage231_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SolGateNeighborhoodLab:
    def __init__(self, root: Path):
        self.root = root
        self.out_dir = root / "reports" / "research_raw"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = root / "data" / "raw"
        self.mod = load_stage231_module(root)
        self.lab = self.mod.SeededConfirmationMatrix(root)
        self.param_map = self.mod.PARAM_MAP

    @staticmethod
    def _recommendation_rank(rec: str) -> int:
        order = {
            "promote_gate_neighborhood": 0,
            "keep_research_gate": 1,
            "discard_gate": 2,
            "base_reference": 3,
            "control_reference": 4,
            "skip": 5,
        }
        return order.get(rec, 9)

    def scaled_param(self, param_id: str, stop_scale: float, trail_scale: float) -> dict[str, float]:
        p = dict(self.param_map[param_id])
        p["stop_atr"] = float(p["stop_atr"] * stop_scale)
        p["trail_atr"] = float(p["trail_atr"] * trail_scale)
        return p

    def metrics_windows_scaled(self, df: pd.DataFrame, long_sig, short_sig, p: dict[str, float], mode: str) -> dict[str, float]:
        full_trades, full_dd = self.lab.backtest(df, long_sig, short_sig, p, mode)
        recent_start = df.index.max() - pd.DateOffset(years=self.lab.recent_years)
        wf_start = df.index.max() - pd.DateOffset(months=self.lab.wf_months)

        recent_df = df[df.index >= recent_start]
        r_mask = df.index >= recent_start
        recent_trades, recent_dd = self.lab.backtest(recent_df, long_sig[r_mask], short_sig[r_mask], p, mode)

        wf_df = df[df.index >= wf_start]
        w_mask = df.index >= wf_start
        wf_trades, wf_dd = self.lab.backtest(wf_df, long_sig[w_mask], short_sig[w_mask], p, mode)

        full = self.lab.metrics_from_trades(full_trades)
        recent = self.lab.metrics_from_trades(recent_trades)
        wf = self.lab.metrics_from_trades(wf_trades)
        return {
            "full_trades": full["trades"],
            "full_win": full["win_rate"],
            "full_ret": full["ret_pct"],
            "full_pf": full["pf"],
            "full_dd": full_dd,
            "full_lev": full["avg_lev"],
            "recent_trades": recent["trades"],
            "recent_win": recent["win_rate"],
            "recent_ret": recent["ret_pct"],
            "recent_pf": recent["pf"],
            "recent_dd": recent_dd,
            "recent_lev": recent["avg_lev"],
            "wf_trades": wf["trades"],
            "wf_win": wf["win_rate"],
            "wf_ret": wf["ret_pct"],
            "wf_pf": wf["pf"],
            "wf_dd": wf_dd,
            "wf_lev": wf["avg_lev"],
        }

    def evaluate_controls(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for ctrl in REFERENCE_CONTROLS:
            p = self.scaled_param(ctrl["param_id"], 1.0, 1.0)
            df = self.lab.get_merged(ctrl["symbol"], ctrl["entry_tf"], ctrl["filter_tf"])
            long_sig, short_sig = self.lab.family_signals(df, ctrl["family"], self.param_map[ctrl["param_id"]])
            metrics = self.metrics_windows_scaled(df, long_sig, short_sig, p, ctrl["mode"])
            row = {
                "control_id": ctrl["control_id"],
                "symbol": ctrl["symbol"],
                "entry_tf": ctrl["entry_tf"],
                "filter_tf": ctrl["filter_tf"],
                "family": ctrl["family"],
                "param_id": ctrl["param_id"],
                "mode": ctrl["mode"],
                "variant": "base_reference",
                "gate_name": "none",
                "confirm_window_bars": 0,
                "helper_set": "",
                "min_votes": 0,
                "stop_profile": ctrl["stop_profile"],
                "stop_scale": 1.0,
                "trail_scale": 1.0,
                "recommendation": "control_reference",
            }
            row.update(metrics)
            rows.append(row)
        return rows

    def run(self) -> dict[str, object]:
        if not (self.raw_dir / f"{SOL_SYMBOL}_{BASE_ENTRY_TF}.csv").exists():
            summary = {
                "status": "SKIP",
                "reason": "missing_5m_raw",
                "message": "当前 live 目录缺少 sol_5m.csv；这一步必须在已有真实 5m raw 的机器上跑。",
            }
            (self.out_dir / "stage232_sol_gate_neighborhood_summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (self.out_dir / "stage232_sol_gate_neighborhood_latest.txt").write_text(
                "[stage232_sol_gate_neighborhood]\nstatus=SKIP\nreason=missing_5m_raw\n", encoding="utf-8"
            )
            pd.DataFrame().to_csv(self.out_dir / "stage232_sol_gate_neighborhood_all.csv", index=False)
            return summary

        df = self.lab.get_merged(SOL_SYMBOL, BASE_ENTRY_TF, BASE_FILTER_TF)
        rows: list[dict[str, object]] = []
        baseline_map: dict[tuple[str, str, str], dict[str, float]] = {}

        for param_id in PARAM_IDS:
            signal_param = self.param_map[param_id]
            base_long, base_short = self.lab.family_signals(df, BASE_FAMILY, signal_param)
            helper_signal_map = {
                fam: self.lab.family_signals(df, fam, signal_param)
                for fam in ["range_revert_grid", "sweep_reclaim", "retest_fail"]
            }
            for mode in MODES:
                for profile in STOP_PROFILES:
                    exec_p = self.scaled_param(param_id, profile["stop_scale"], profile["trail_scale"])
                    metrics = self.metrics_windows_scaled(df, base_long, base_short, exec_p, mode)
                    base_row = {
                        "symbol": SOL_SYMBOL,
                        "entry_tf": BASE_ENTRY_TF,
                        "filter_tf": BASE_FILTER_TF,
                        "family": BASE_FAMILY,
                        "param_id": param_id,
                        "mode": mode,
                        "variant": "base",
                        "gate_name": "none",
                        "confirm_window_bars": 0,
                        "helper_set": "",
                        "min_votes": 0,
                        "stop_profile": profile["label"],
                        "stop_scale": profile["stop_scale"],
                        "trail_scale": profile["trail_scale"],
                        "avg_long_votes": 0.0,
                        "avg_short_votes": 0.0,
                        "signal_long_count": int(base_long.sum()),
                        "signal_short_count": int(base_short.sum()),
                        "recommendation": "base_reference",
                    }
                    base_row.update(metrics)
                    rows.append(base_row)
                    baseline_map[(param_id, mode, profile["label"])] = metrics

                    for spec in GATE_VARIANTS:
                        gated_long, gated_short, long_votes, short_votes = self.lab.apply_vote_gate(
                            df=df,
                            base_long=base_long,
                            base_short=base_short,
                            helper_pairs=[helper_signal_map[h] for h in spec["helpers"]],
                            min_votes=spec["min_votes"],
                            window=spec["window"],
                        )
                        gate_metrics = self.metrics_windows_scaled(df, gated_long, gated_short, exec_p, mode)
                        row = {
                            "symbol": SOL_SYMBOL,
                            "entry_tf": BASE_ENTRY_TF,
                            "filter_tf": BASE_FILTER_TF,
                            "family": BASE_FAMILY,
                            "param_id": param_id,
                            "mode": mode,
                            "variant": f"{spec['variant']}_{spec['window']}b_{profile['label']}",
                            "gate_name": spec["variant"],
                            "confirm_window_bars": spec["window"],
                            "helper_set": ",".join(spec["helpers"]),
                            "min_votes": spec["min_votes"],
                            "stop_profile": profile["label"],
                            "stop_scale": profile["stop_scale"],
                            "trail_scale": profile["trail_scale"],
                            "signal_long_count": int(gated_long.sum()),
                            "signal_short_count": int(gated_short.sum()),
                            "avg_long_votes": float(long_votes[base_long].mean()) if base_long.any() else 0.0,
                            "avg_short_votes": float(short_votes[base_short].mean()) if base_short.any() else 0.0,
                        }
                        row.update(gate_metrics)
                        rows.append(row)

        ctrl_rows = self.evaluate_controls()
        rows.extend(ctrl_rows)
        df_rows = pd.DataFrame(rows)
        df_rows.to_csv(self.out_dir / "stage232_sol_gate_neighborhood_all.csv", index=False)

        for idx, row in df_rows.iterrows():
            if row["recommendation"] in {"base_reference", "control_reference"}:
                continue
            base = baseline_map[(row["param_id"], row["mode"], row["stop_profile"])]
            base_recent_ret = float(base["recent_ret"])
            base_recent_win = float(base["recent_win"])
            base_recent_pf = float(base["recent_pf"])
            base_recent_trades = int(base["recent_trades"])
            base_wf_pf = float(base["wf_pf"])
            base_wf_trades = int(base["wf_trades"])

            keep_ratio = float(row["recent_trades"] / base_recent_trades) if base_recent_trades else 0.0
            ret_ratio = float(row["recent_ret"] / base_recent_ret) if base_recent_ret > 0 else 0.0
            win_delta = float(row["recent_win"] - base_recent_win)
            pf_delta = float(row["recent_pf"] - base_recent_pf)

            df_rows.at[idx, "base_recent_ret"] = base_recent_ret
            df_rows.at[idx, "base_recent_win"] = base_recent_win
            df_rows.at[idx, "base_recent_pf"] = base_recent_pf
            df_rows.at[idx, "base_recent_trades"] = base_recent_trades
            df_rows.at[idx, "base_wf_pf"] = base_wf_pf
            df_rows.at[idx, "base_wf_trades"] = base_wf_trades
            df_rows.at[idx, "keep_ratio_recent"] = keep_ratio
            df_rows.at[idx, "ret_ratio_recent"] = ret_ratio
            df_rows.at[idx, "win_delta_recent"] = win_delta
            df_rows.at[idx, "pf_delta_recent"] = pf_delta

            promote = (
                row["recent_trades"] >= max(8, ceil(base_recent_trades * 0.18))
                and row["wf_trades"] >= max(5, ceil(base_wf_trades * 0.18))
                and row["recent_pf"] >= max(1.60, base_recent_pf * 1.10)
                and row["wf_pf"] >= max(1.20, base_wf_pf * 0.90)
                and row["recent_ret"] >= max(12.0, base_recent_ret * 0.18)
                and win_delta >= 5.0
                and 0.15 <= keep_ratio <= 0.70
            )
            keep = (
                row["recent_pf"] >= 1.30
                and row["wf_pf"] >= 1.00
                and row["recent_ret"] > 0
                and keep_ratio >= 0.10
            )
            if promote:
                rec = "promote_gate_neighborhood"
            elif keep:
                rec = "keep_research_gate"
            else:
                rec = "discard_gate"
            df_rows.at[idx, "recommendation"] = rec

        df_rows["recommendation_rank"] = df_rows["recommendation"].map(self._recommendation_rank)
        df_rows.to_csv(self.out_dir / "stage232_sol_gate_neighborhood_all.csv", index=False)

        promoted = df_rows[df_rows["recommendation"] == "promote_gate_neighborhood"].copy()
        research = df_rows[df_rows["recommendation"] == "keep_research_gate"].copy()
        controls = df_rows[df_rows["recommendation"].isin(["base_reference", "control_reference"])].copy()

        sort_cols = ["recommendation_rank", "recent_pf", "recent_win", "wf_pf", "recent_ret"]
        sort_asc = [True, False, False, False, False]
        promoted.sort_values(sort_cols, ascending=sort_asc, inplace=True)
        research.sort_values(sort_cols, ascending=sort_asc, inplace=True)

        best_by_mode: dict[str, list[dict[str, object]]] = {}
        for mode in MODES:
            sub = promoted[promoted["mode"] == mode].copy()
            if sub.empty:
                sub = research[research["mode"] == mode].copy()
            sub.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False], inplace=True)
            best_by_mode[mode] = sub.head(3).to_dict(orient="records") if not sub.empty else []

        summary = {
            "status": "OK",
            "goal": "expand SOL 5m/15m gate_range_2b and gate_vote1_micro_2b neighborhood without moving runtime",
            "ranking_policy": {
                "primary": "recent_2y_win_pf_ret",
                "secondary": "wf_12m_pf",
                "full_sample": "soft_constraint_only",
            },
            "tested_rows": int(len(df_rows)),
            "promote_total": int(len(promoted)),
            "gate_variants": GATE_VARIANTS,
            "stop_profiles": STOP_PROFILES,
            "best_by_mode": best_by_mode,
            "top_promoted": promoted.head(10).to_dict(orient="records"),
            "top_research": research.head(10).to_dict(orient="records"),
            "controls": controls.to_dict(orient="records"),
        }
        (self.out_dir / "stage232_sol_gate_neighborhood_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        lines: list[str] = []
        lines.append("[stage232_sol_gate_neighborhood]")
        lines.append("goal=只扩 SOL 5m/15m 的 promoted gates 邻域；BTC/BNB/ETH 裸引擎保持不动")
        lines.append(f"tested_rows={len(df_rows)}")
        lines.append(f"promote_total={len(promoted)}")
        lines.append("ranking=近2年胜率/近2年PF/近2年收益优先 -> WF PF | keep_ratio 约束 | 6年仅软约束")
        lines.append("")
        lines.append("[controls]")
        base_controls = controls[controls["symbol"] == "sol"].copy()
        base_controls.sort_values(["entry_tf", "recent_pf", "recent_win"], ascending=[True, False, False], inplace=True)
        for _, r in base_controls.iterrows():
            lines.append(
                f"- {r['symbol']} | {r['entry_tf']}/{r['filter_tf']} | {r['family']} | {r['param_id']} | {r['mode']} | {r['variant']} | {r['stop_profile']} "
                f"| recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                f"| wf={r['wf_ret']:.2f}%/{r['wf_win']:.2f}%/PF{r['wf_pf']:.3f}"
            )
        lines.append("")
        lines.append("[top_promoted]")
        if promoted.empty:
            lines.append("- none")
        else:
            for _, r in promoted.head(8).iterrows():
                lines.append(
                    f"- {r['gate_name']} | {r['param_id']} | {r['mode']} | win={int(r['confirm_window_bars'])}b | {r['stop_profile']} "
                    f"| recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                    f"| wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | keep_ratio={r.get('keep_ratio_recent', 0.0):.2f}"
                )
        lines.append("")
        lines.append("[best_by_mode]")
        for mode, items in best_by_mode.items():
            lines.append(f"{mode}=")
            if not items:
                lines.append("- none")
            else:
                for r in items:
                    lines.append(
                        f"- {r['gate_name']} | {r['param_id']} | win={int(r['confirm_window_bars'])}b | {r['stop_profile']} "
                        f"| recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                        f"| wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f}"
                    )
        lines.append("")
        lines.append("[top_research]")
        if research.empty:
            lines.append("- none")
        else:
            for _, r in research.head(8).iterrows():
                lines.append(
                    f"- {r['gate_name']} | {r['param_id']} | {r['mode']} | win={int(r['confirm_window_bars'])}b | {r['stop_profile']} "
                    f"| recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} "
                    f"| wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | keep_ratio={r.get('keep_ratio_recent', 0.0):.2f}"
                )
        (self.out_dir / "stage232_sol_gate_neighborhood_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return summary


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    lab = SolGateNeighborhoodLab(Path(args.project_dir))
    lab.run()


if __name__ == "__main__":
    main()
