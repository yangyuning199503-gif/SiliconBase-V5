#!/usr/bin/env python3
"""
清理向量库中 ui_element collection 的乱码数据
直接连接 ChromaDB，绕过 PostgreSQL
"""
import asyncio
import sys


async def cleanup_ui_element_collection():
    try:
        import chromadb
        client = await chromadb.AsyncHttpClient(host="localhost", port=8000)

        # 列出所有 collections
        collections = await client.list_collections()
        print(f"[INFO] ChromaDB 现有 collections: {[c.name if hasattr(c, 'name') else str(c) for c in collections]}")

        # 查找 ui_element collection（ChromaDB 返回的是 Collection 对象或字符串）
        target_name = "ui_element"
        found = False
        for c in collections:
            name = c.name if hasattr(c, 'name') else str(c)
            if name == target_name:
                found = True
                break

        if not found:
            print(f"[INFO] {target_name} collection 不存在，无需清理")
            return 0

        # 获取 collection 并统计
        col = await client.get_collection(target_name)
        count = await col.count()
        print(f"[INFO] {target_name} collection 当前记录数: {count}")

        # 删除整个 collection
        await client.delete_collection(target_name)
        print(f"[PASS] {target_name} collection 已删除")

        # 验证删除
        collections_after = await client.list_collections()
        names_after = [c.name if hasattr(c, 'name') else str(c) for c in collections_after]
        print(f"[INFO] 删除后 collections: {names_after}")
        if target_name not in names_after:
            print("[PASS] 验证通过: ui_element 已不存在")
            return 0
        else:
            print("[FAIL] 验证失败: ui_element 仍然存在")
            return 1

    except ImportError:
        print("[FAIL] chromadb 未安装")
        return 1
    except Exception as e:
        print(f"[FAIL] 清理失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(cleanup_ui_element_collection())
    sys.exit(exit_code)
