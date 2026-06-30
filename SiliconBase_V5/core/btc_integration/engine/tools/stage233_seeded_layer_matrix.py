from __future__ import annotations

import argparse
import importlib.util
import json
from math import ceil
from pathlib import Path

import pandas as pd

STOP_PROFILES = [
    {"label": "base", "stop_scale": 1.00, "trail_scale": 1.00},
    {"label": "tight", "stop_scale": 0.92, "trail_scale": 0.92},
]

VARIANTS = [
    {"variant": "base", "helpers": [], "min_votes": 0, "window": 1},
    {"variant": "gate_range_1b", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 1},
    {"variant": "gate_range_2b", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 2},
    {"variant": "gate_range_3b", "helpers": ["range_revert_grid"], "min_votes": 1, "window": 3},
    {"variant": "gate_vote1_micro_1b", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 1},
    {"variant": "gate_vote1_micro_2b", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 2},
    {"variant": "gate_vote1_micro_3b", "helpers": ["sweep_reclaim", "retest_fail", "range_revert_grid"], "min_votes": 1, "window": 3},
    {"variant": "gate_retest_2b", "helpers": ["retest_fail"], "min_votes": 1, "window": 2},
    {"variant": "gate_sweep_2b", "helpers": ["sweep_reclaim"], "min_votes": 1, "window": 2},
    {"variant": "gate_trend_2b", "helpers": ["ma_macd_bb"], "min_votes": 1, "window": 2},
    {"variant": "gate_squeeze_2b", "helpers": ["squeeze_pullback"], "min_votes": 1, "window": 2},
]

HELPER_FAMILIES = sorted({h for spec in VARIANTS for h in spec["helpers"]})

SEED_VARIANT_MAP = {
    "btc_fast_short_engine": {"base", "gate_range_1b", "gate_range_2b", "gate_vote1_micro_1b", "gate_vote1_micro_2b", "gate_sweep_2b", "gate_retest_2b"},
    "bnb_fast_dual_engine": {"base", "gate_range_1b", "gate_range_2b", "gate_vote1_micro_1b", "gate_vote1_micro_2b", "gate_trend_2b", "gate_squeeze_2b"},
    "eth_slow_dual_engine": {"base", "gate_range_1b", "gate_range_2b", "gate_vote1_micro_1b", "gate_vote1_micro_2b", "gate_sweep_2b"},
    "sol_fast_dual_engine": {"base", "gate_range_1b", "gate_range_2b", "gate_range_3b", "gate_vote1_micro_1b", "gate_vote1_micro_2b", "gate_vote1_micro_3b"},
}


def load_stage231_module(root: Path):
    path = root / "tools" / "stage231_seeded_confirmation_matrix.py"
    spec = importlib.util.spec_from_file_location("stage231_seeded_confirmation_matrix", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SeededLayerMatrix:
    def __init__(self, root: Path):
        self.root = root
        self.out_dir = root / "reports" / "research_raw"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.mod = load_stage231_module(root)
        self.lab = self.mod.SeededConfirmationMatrix(root)
        self.param_map = self.mod.PARAM_MAP
        self.seeds = [s for s in self.mod.SEED_LANES if s.get("role") == "engine"]
        self.references = [s for s in self.mod.SEED_LANES if s.get("role") == "confirm_reference"]

    @staticmethod
    def rec_rank(rec: str) -> int:
        order = {
            "promote_hard_gate": 0,
            "promote_soft_overlay": 1,
            "keep_research_gate": 2,
            "base_reference": 3,
            "confirm_reference": 4,
            "discard_gate": 5,
            "skip": 6,
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

    def evaluate_seed(self, seed: dict[str, object]) -> list[dict[str, object]]:
        df = self.lab.get_merged(seed["symbol"], seed["entry_tf"], seed["filter_tf"])
        signal_param = self.param_map[seed["param_id"]]
        base_long, base_short = self.lab.family_signals(df, seed["family"], signal_param)
        helper_signal_map = {fam: self.lab.family_signals(df, fam, signal_param) for fam in HELPER_FAMILIES}
        rows: list[dict[str, object]] = []
        enabled = SEED_VARIANT_MAP.get(seed["seed_id"], {v["variant"] for v in VARIANTS})
        for profile in STOP_PROFILES:
            exec_p = self.scaled_param(seed["param_id"], profile["stop_scale"], profile["trail_scale"])
            for spec in VARIANTS:
                if spec["variant"] not in enabled:
                    continue
                if spec["variant"] == "base":
                    long_sig, short_sig = base_long, base_short
                    long_votes = short_votes = [0] * len(df)
                else:
                    long_sig, short_sig, long_votes, short_votes = self.lab.apply_vote_gate(
                        df=df,
                        base_long=base_long,
                        base_short=base_short,
                        helper_pairs=[helper_signal_map[h] for h in spec["helpers"]],
                        min_votes=spec["min_votes"],
                        window=spec["window"],
                    )
                metrics = self.metrics_windows_scaled(df, long_sig, short_sig, exec_p, seed["mode"])
                row = {
                    "seed_id": seed["seed_id"],
                    "symbol": seed["symbol"],
                    "entry_tf": seed["entry_tf"],
                    "filter_tf": seed["filter_tf"],
                    "family": seed["family"],
                    "param_id": seed["param_id"],
                    "mode": seed["mode"],
                    "variant": spec["variant"],
                    "gate_name": spec["variant"].replace(f"_{spec['window']}b", "") if spec["variant"] != "base" else "none",
                    "confirm_window_bars": spec["window"] if spec["variant"] != "base" else 0,
                    "helper_set": ",".join(spec["helpers"]),
                    "min_votes": spec["min_votes"],
                    "stop_profile": profile["label"],
                    "stop_scale": profile["stop_scale"],
                    "trail_scale": profile["trail_scale"],
                    "signal_long_count": int(sum(long_sig)),
                    "signal_short_count": int(sum(short_sig)),
                    "avg_long_votes": float(pd.Series(long_votes)[pd.Series(base_long)].mean()) if spec["helpers"] and pd.Series(base_long).any() else 0.0,
                    "avg_short_votes": float(pd.Series(short_votes)[pd.Series(base_short)].mean()) if spec["helpers"] and pd.Series(base_short).any() else 0.0,
                    "recommendation": "base_reference" if spec["variant"] == "base" else "pending",
                }
                row.update(metrics)
                rows.append(row)
        return rows

    def evaluate_reference(self, seed: dict[str, object]) -> dict[str, object]:
        df = self.lab.get_merged(seed["symbol"], seed["entry_tf"], seed["filter_tf"])
        p = self.scaled_param(seed["param_id"], 1.0, 1.0)
        long_sig, short_sig = self.lab.family_signals(df, seed["family"], self.param_map[seed["param_id"]])
        metrics = self.metrics_windows_scaled(df, long_sig, short_sig, p, seed["mode"])
        row = {
            "seed_id": seed["seed_id"],
            "symbol": seed["symbol"],
            "entry_tf": seed["entry_tf"],
            "filter_tf": seed["filter_tf"],
            "family": seed["family"],
            "param_id": seed["param_id"],
            "mode": seed["mode"],
            "variant": "confirm_reference",
            "gate_name": "none",
            "confirm_window_bars": 0,
            "helper_set": "",
            "min_votes": 0,
            "stop_profile": "base",
            "stop_scale": 1.0,
            "trail_scale": 1.0,
            "signal_long_count": int(sum(long_sig)),
            "signal_short_count": int(sum(short_sig)),
            "avg_long_votes": 0.0,
            "avg_short_votes": 0.0,
            "recommendation": "confirm_reference",
        }
        row.update(metrics)
        return row

    def classify(self, df_rows: pd.DataFrame) -> pd.DataFrame:
        base_rows = df_rows[df_rows["variant"] == "base"].copy()
        base_map = {
            (r["seed_id"], r["stop_profile"]): r
            for _, r in base_rows.iterrows()
        }
        for idx, row in df_rows.iterrows():
            if row["recommendation"] in {"base_reference", "confirm_reference"}:
                continue
            base = base_map[(row["seed_id"], row["stop_profile"])]
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
            dd_delta = float(row["recent_dd"] - base["recent_dd"])

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
            df_rows.at[idx, "dd_delta_recent"] = dd_delta

            promote_hard = (
                row["recent_trades"] >= max(8, ceil(base_recent_trades * 0.18))
                and row["wf_trades"] >= max(5, ceil(base_wf_trades * 0.18))
                and row["recent_pf"] >= max(1.40, base_recent_pf * 1.08)
                and row["wf_pf"] >= max(1.00, base_wf_pf * 0.95)
                and row["recent_ret"] >= max(8.0, base_recent_ret * 0.12)
                and win_delta >= 4.0
                and 0.12 <= keep_ratio <= 0.75
            )
            promote_soft = (
                row["recent_pf"] >= max(1.25, base_recent_pf * 1.05)
                and row["wf_pf"] >= max(0.95, base_wf_pf * 0.85)
                and row["recent_ret"] > 0
                and win_delta >= 2.0
                and keep_ratio >= 0.08
            )
            keep_research = (
                row["recent_pf"] >= 1.15
                and row["wf_pf"] >= 0.90
                and row["recent_ret"] > 0
                and keep_ratio >= 0.05
            )
            if promote_hard:
                rec = "promote_hard_gate"
            elif promote_soft:
                rec = "promote_soft_overlay"
            elif keep_research:
                rec = "keep_research_gate"
            else:
                rec = "discard_gate"
            df_rows.at[idx, "recommendation"] = rec
        df_rows["recommendation_rank"] = df_rows["recommendation"].map(self.rec_rank)
        return df_rows

    def run(self) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        for seed in self.seeds:
            rows.extend(self.evaluate_seed(seed))
        for ref in self.references:
            rows.append(self.evaluate_reference(ref))

        df_rows = pd.DataFrame(rows)
        df_rows = self.classify(df_rows)
        df_rows.to_csv(self.out_dir / "stage233_seeded_layer_matrix_all.csv", index=False)

        hard = df_rows[df_rows["recommendation"] == "promote_hard_gate"].copy()
        soft = df_rows[df_rows["recommendation"] == "promote_soft_overlay"].copy()
        research = df_rows[df_rows["recommendation"] == "keep_research_gate"].copy()
        controls = df_rows[df_rows["recommendation"].isin(["base_reference", "confirm_reference"])].copy()

        best_by_seed: dict[str, dict[str, object]] = {}
        for seed in self.seeds:
            sid = seed["seed_id"]
            base = df_rows[(df_rows["seed_id"] == sid) & (df_rows["variant"] == "base")].iloc[0].to_dict()
            cand = df_rows[(df_rows["seed_id"] == sid) & (df_rows["variant"] != "base")].copy()
            cand.sort_values(["recommendation_rank", "recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[True, False, False, False, False], inplace=True)
            top = cand.iloc[0].to_dict() if not cand.empty else None
            best_by_seed[sid] = {
                "base": base,
                "top_candidate": top,
            }

        summary = {
            "status": "OK",
            "goal": "separate engine / hard confirmation / soft confirmation for the 4 research seed lanes without moving runtime",
            "tested_rows": int(len(df_rows)),
            "hard_gate_total": int(len(hard)),
            "soft_overlay_total": int(len(soft)),
            "research_keep_total": int(len(research)),
            "best_by_seed": best_by_seed,
            "top_hard": hard.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False]).head(12).to_dict(orient="records"),
            "top_soft": soft.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False]).head(12).to_dict(orient="records"),
            "top_research": research.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False]).head(12).to_dict(orient="records"),
            "controls": controls.to_dict(orient="records"),
        }
        (self.out_dir / "stage233_seeded_layer_matrix_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        lines: list[str] = []
        lines.append("[stage233_seeded_layer_matrix]")
        lines.append("goal=四条主攻 seed lanes 做三层分离：裸引擎 / 硬确认 / 软确认；runtime 保持不动")
        lines.append(f"tested_rows={len(df_rows)}")
        lines.append(f"hard_gate_total={len(hard)}")
        lines.append(f"soft_overlay_total={len(soft)}")
        lines.append(f"research_keep_total={len(research)}")
        lines.append("ranking=先看近2年PF/胜率/收益，再看WF PF；6年继续只做软约束")
        lines.append("")
        lines.append("[best_by_seed]")
        for seed in self.seeds:
            sid = seed["seed_id"]
            base = best_by_seed[sid]["base"]
            top = best_by_seed[sid]["top_candidate"]
            lines.append(
                f"- {sid} | base={base['entry_tf']}/{base['filter_tf']} {base['family']} {base['param_id']} {base['mode']} | "
                f"recent={base['recent_ret']:.2f}%/{base['recent_win']:.2f}%/PF{base['recent_pf']:.3f} | "
                f"wf={base['wf_ret']:.2f}%/PF{base['wf_pf']:.3f}"
            )
            if top is not None:
                lines.append(
                    f"  -> top={top['recommendation']} {top['variant']} {top['stop_profile']} | "
                    f"recent={top['recent_ret']:.2f}%/{top['recent_win']:.2f}%/PF{top['recent_pf']:.3f} | "
                    f"wf={top['wf_ret']:.2f}%/PF{top['wf_pf']:.3f} | keep={top.get('keep_ratio_recent', 0.0):.2f}"
                )
        lines.append("")
        lines.append("[top_hard]")
        if hard.empty:
            lines.append("- none")
        else:
            hard_sorted = hard.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False])
            for _, r in hard_sorted.head(10).iterrows():
                lines.append(
                    f"- {r['seed_id']} | {r['variant']} | {r['stop_profile']} | recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} | wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | keep={r.get('keep_ratio_recent', 0.0):.2f}"
                )
        lines.append("")
        lines.append("[top_soft]")
        if soft.empty:
            lines.append("- none")
        else:
            soft_sorted = soft.sort_values(["recent_pf", "recent_win", "wf_pf", "recent_ret"], ascending=[False, False, False, False])
            for _, r in soft_sorted.head(10).iterrows():
                lines.append(
                    f"- {r['seed_id']} | {r['variant']} | {r['stop_profile']} | recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} | wf={r['wf_ret']:.2f}%/PF{r['wf_pf']:.3f} | keep={r.get('keep_ratio_recent', 0.0):.2f}"
                )
        lines.append("")
        lines.append("[confirm_references]")
        for _, r in controls.iterrows():
            lines.append(
                f"- {r['seed_id']} | {r['entry_tf']}/{r['filter_tf']} | {r['family']} | {r['param_id']} | {r['mode']} | recent={r['recent_ret']:.2f}%/{r['recent_win']:.2f}%/PF{r['recent_pf']:.3f} | wf={r['wf_ret']:.2f}%/{r['wf_win']:.2f}%/PF{r['wf_pf']:.3f}"
            )
        (self.out_dir / "stage233_seeded_layer_matrix_latest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return summary


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    lab = SeededLayerMatrix(Path(args.project_dir))
    lab.run()


if __name__ == "__main__":
    main()
