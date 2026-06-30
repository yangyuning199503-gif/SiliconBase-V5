#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p "$ROOT/reports/research_raw"
STAMP_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
cat > "$ROOT/reports/research_raw/stage105_joint_parallel_latest.txt" <<EOF
Stage105 主线+第二分支并行推进
原则：主线和支线一起调整，但不改变双终端规则；6年仅作软约束，判断以近2年 + WF 为主；先激进扩机会，再保守收口。

generated_at_utc=${STAMP_UTC}

=== 主线有效口径（沿用已验证结果，不采用 stage102 那份异常 0 笔统计） ===
- keep_live: mainline_live_base
- shadow_priority_1: combo_sr_soft_adx26_cd6_lb24_zone028_ref
- shadow_priority_2: combo_sr_soft_adx32_cd5_lb20_zone025
- 解释: 主线继续 live_base；提频继续 shadow 观察，不直接切 live。

=== 第二分支整体 book ===
- runtime_book: BTC+ETH 资产腿预览
- version_target: r250_branch_demo_asset_integrated__btc035_eth065_preview_v1
- btc_weight=0.35 | eth_weight=0.65 | sol=research_only
- BTC: 多空一体低权重接入，不因为 ETH short fast 仍最强就删除 BTC 路径。
- ETH: 继续保留 eth_short_shock_fast_lb16_atr052_adx22_s078 主导。
- SOL: 继续 research_only，不接当前 demo。

=== 当前动作 ===
- 主线：保持原运行，不动 okxm。
- 分支：只切到 BTC+ETH 资产腿预览，继续用 okxb。
- 导出：stage105_joint_parallel_latest.zip
EOF

echo "[1/3] 写入并行推进摘要 ..."
echo "[2/3] 强制切第二分支到 BTC+ETH 资产腿预览 ..."
bash "$ROOT/switch_branch_demo_to_asset_integrated.sh"

echo "[3/3] 导出联合观察包 ..."
bash "$ROOT/export_stage105_joint_preview.sh"
