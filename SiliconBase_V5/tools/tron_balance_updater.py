#!/usr/bin/env python3
"""
原子工具：波场持币余额更新器
读取Excel中的地址列表，查询指定代币余额并更新表格
"""
import asyncio
from pathlib import Path

from core.base_tool import BaseTool
from core.config import config
from core.error_codes import FILE_NOT_FOUND, INVALID_PARAMS, TOOL_EXECUTION_ERROR, format_error
from core.logger import logger


class TronBalanceUpdater(BaseTool):
    tool_id = "tron_balance_updater"
    name = "波场持币余额更新"
    description = "读取Excel中的波场地址列表，查询指定代币余额，更新C列并计算总和"
    require_confirmation = True  # 操作文件，需用户确认

    # 从配置加载参数，也可允许用户动态传入
    input_schema = {
        "type": "object",
        "properties": {
            "excel_path": {"type": "string", "description": "Excel文件完整路径，默认使用配置中的路径"},
            "target_token": {"type": "string", "description": "代币合约地址，默认使用配置中的地址"},
            "summary_sheet": {"type": "string", "description": "汇总工作表名称，默认使用配置中的名称"},
            "delay": {"type": "number", "description": "请求间隔秒数，默认0.2"},
            "retry": {"type": "integer", "description": "重试次数，默认2"}
        }
    }

    async def _execute_async(self, **kwargs) -> dict:
        """原生异步执行：aiohttp 查询余额 + to_thread 处理 Excel I/O"""
        excel_path = kwargs.get("excel_path") or config.get("tools.tron_balance_updater.excel_path")
        target_token = kwargs.get("target_token") or config.get("tools.tron_balance_updater.target_token")
        summary_sheet = kwargs.get("summary_sheet") or config.get("tools.tron_balance_updater.summary_sheet", "合计")
        delay = kwargs.get("delay") or config.get("tools.tron_balance_updater.delay", 0.2)
        retry = kwargs.get("retry") or config.get("tools.tron_balance_updater.retry", 2)
        api_key = kwargs.get("api_key") or config.get("tools.tron_balance_updater.api_key", "")

        if not excel_path:
            return format_error(INVALID_PARAMS, detail="未指定Excel文件路径，请在配置中设置 tools.tron_balance_updater.excel_path")
        if not target_token:
            return format_error(INVALID_PARAMS, detail="未指定代币合约地址，请在配置中设置 tools.tron_balance_updater.target_token")

        excel_file = Path(excel_path)
        if not excel_file.exists():
            return format_error(FILE_NOT_FOUND, path=str(excel_file))

        try:
            result = await self._update_balances_async(
                str(excel_file), target_token, summary_sheet, delay, retry, api_key
            )
            return {
                "success": True,
                "error_code": None,
                "user_message": f"持币数据更新完成，总计 {result['total']} 个地址处理成功",
                "data": result
            }
        except Exception as e:
            logger.exception(f"波场余额更新工具执行失败: {e}")
            return format_error(TOOL_EXECUTION_ERROR, detail=str(e))

    async def _update_balances_async(self, excel_path, target_token, summary_sheet, delay, retry, api_key):
        """核心异步处理逻辑"""
        import aiohttp
        import pandas as pd

        # 1. Excel 读取（文件 I/O → to_thread）
        excel_dict = await asyncio.to_thread(
            pd.read_excel, excel_path, sheet_name=None, header=None, engine="openpyxl"
        )
        summary_data = []
        exclude_sheets = [summary_sheet, "核心地址", "查重"]

        # 2. 收集所有需要查询的地址
        queries = []  # [(sheet_name, row_idx, address)]
        for sheet_name, df in excel_dict.items():
            if sheet_name in exclude_sheets:
                logger.info(f"跳过工作表: {sheet_name}")
                continue
            for row_idx in range(1, len(df)):
                address = df.iloc[row_idx, 0]
                if pd.isna(address) or str(address).strip() == "":
                    continue
                queries.append((sheet_name, row_idx, str(address).strip()))

        url = "https://apilist.tronscanapi.com/api/account/token_asset_overview"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "TRON-PRO-API-KEY": api_key
        }
        timeout = aiohttp.ClientTimeout(total=15)

        balance_map = {}  # (sheet_name, row_idx) -> balance
        BATCH_SIZE = 5

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for i in range(0, len(queries), BATCH_SIZE):
                batch = queries[i:i + BATCH_SIZE]
                tasks = [
                    self._fetch_balance_with_retry(session, url, address, target_token, retry)
                    for _, _, address in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for (sheet_name, row_idx, _), result in zip(batch, results, strict=False):
                    if isinstance(result, Exception):
                        balance_map[(sheet_name, row_idx)] = f"查询失败: {result}"
                    else:
                        balance_map[(sheet_name, row_idx)] = result
                if delay > 0:
                    await asyncio.sleep(delay)

        # 4. 更新 DataFrame
        for sheet_name, df in excel_dict.items():
            if sheet_name in exclude_sheets:
                continue
            c_vals = []
            for row_idx in range(1, len(df)):
                key = (sheet_name, row_idx)
                if key in balance_map:
                    bal = balance_map[key]
                    df.iloc[row_idx, 2] = bal
                    if isinstance(bal, (int, float)) and not pd.isna(bal):
                        c_vals.append(int(bal))
                else:
                    df.iloc[row_idx, 2] = 0

            total = sum(c_vals)
            if df.shape[1] <= 4:
                df[4] = ""
            df.iloc[1, 4] = total
            excel_dict[sheet_name] = df
            summary_data.append({"名称": sheet_name, "总量": total})

        # 5. 更新汇总表
        if summary_sheet in excel_dict:
            summary_df = excel_dict[summary_sheet]
            for row_idx in range(1, len(summary_df)):
                name = summary_df.iloc[row_idx, 0]
                if pd.isna(name):
                    continue
                for item in summary_data:
                    if item["名称"] == name:
                        if summary_df.shape[1] <= 3:
                            summary_df[3] = ""
                        summary_df.iloc[row_idx, 3] = item["总量"]
                        break
            d_total = sum(item["总量"] for item in summary_data)
            if summary_df.shape[1] <= 5:
                summary_df[5] = ""
            summary_df.iloc[1, 5] = d_total
            excel_dict[summary_sheet] = summary_df
        else:
            logger.warning(f"未找到汇总表 {summary_sheet}，跳过汇总更新")

        # 6. 保存文件（文件 I/O → to_thread）
        def _save():
            with pd.ExcelWriter(excel_path, engine="openpyxl", mode="w") as writer:
                for sheet_name, df in excel_dict.items():
                    df.to_excel(writer, sheet_name=sheet_name, index=False, header=False)

        await asyncio.to_thread(_save)
        return {"total": len(excel_dict) - len(exclude_sheets)}

    async def _fetch_balance_with_retry(self, session, url, address, target_token, max_retry):
        """异步查询单个地址余额（带重试）"""
        params = {"address": address}
        last_exc = None
        for attempt in range(max_retry + 1):
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:
                        wait = 0.5 * (2 ** attempt)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    data = await resp.json()
                    for token in data.get("data", []):
                        if token.get("tokenId") == target_token:
                            balance_raw = int(token.get("balance", 0))
                            decimals = int(token.get("tokenDecimal", 18))
                            return int(balance_raw / (10 ** decimals))
                    return 0
            except Exception as e:
                last_exc = e
                if attempt < max_retry:
                    wait = 0.5 * (2 ** attempt)
                    await asyncio.sleep(wait)
                else:
                    raise last_exc from e
        return f"查询失败: {last_exc}"
