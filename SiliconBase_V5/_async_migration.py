#!/usr/bin/env python3
"""
一次性异步化改造脚本 - Phase 1: memory.py 核心层
目标：删除同步包装器，统一为纯 async 接口
"""

def fix_memory_py():
    with open('core/memory/memory.py', encoding='utf-8') as f:
        content = f.read()

    # 1. 删除 nest_asyncio
    content = content.replace(
        'import nest_asyncio; nest_asyncio.apply()  # 【P1-Asyncify】允许嵌套事件循环\n',
        ''
    )

    # 2. 删除 UserMemoryStore.add() 同步包装器 (line 332-345)
    old_add_sync = '''    def add(self, layer: str, content: dict, expire_days: Optional[int] = None,
            mem_type: str = "general", context: Dict = None, scene: str = "",
            rating: int = 0, sync_vector: bool = True,
            value_assessment: Dict = None,
            source: str = "system",
            creator: str = "system") -> str:
        """添加记忆——同步包装器（向后兼容）。底层调用 add_async()。"""
        return asyncio.run(self.add_async(
            layer=layer, content=content, expire_days=expire_days,
            mem_type=mem_type, context=context, scene=scene,
            rating=rating, sync_vector=sync_vector,
            value_assessment=value_assessment,
            source=source, creator=creator
        ))

'''
    content = content.replace(old_add_sync, '')

    # 3. add_async -> add
    content = content.replace('async def add_async(self, layer: str,', 'async def add(self, layer: str,')

    # 4. 删除 UserMemoryStore.query() 同步包装器
    old_query_sync = '''    def query(self, layer: Optional[str] = None, filters: Optional[Dict] = None,
              limit: int = 10, dimension_weights: Optional[Dict[str, float]] = None,
              query_text: Optional[str] = None,
              use_semantic_search: bool = True,
              semantic_weight: float = 0.6) -> List[Dict]:
        """查询记忆——同步包装器（向后兼容）。底层调用 query_async()。"""
        return asyncio.run(self.query_async(
            layer=layer, filters=filters, limit=limit,
            dimension_weights=dimension_weights, query_text=query_text,
            use_semantic_search=use_semantic_search, semantic_weight=semantic_weight
        ))

'''
    content = content.replace(old_query_sync, '')

    # 5. query_async -> query
    content = content.replace('async def query_async(self, layer: Optional[str] = None,', 'async def query(self, layer: Optional[str] = None,')

    # 6. 删除 UserMemoryStore.update() 同步包装器
    old_update_sync = '''    def update(self, mem_id: str, updates: Dict) -> bool:
        """
        更新记忆——同步包装器（向后兼容）。
        【P1-Asyncify】底层调用 update_async()，通过 asyncio.run 桥接。
        优先使用异步 update_async() 以避免阻塞事件循环。
        """
        return asyncio.run(self.update_async(mem_id, updates))

'''
    content = content.replace(old_update_sync, '')

    # 7. update_async -> update
    content = content.replace('async def update_async(self, mem_id: str, updates: Dict) -> bool:', 'async def update(self, mem_id: str, updates: Dict) -> bool:')

    # 8. 删除 UserMemoryStore.delete() 同步包装器
    old_delete_sync = '''    def delete(self, mem_id: str, sync_vector: bool = True) -> bool:
        """删除记忆——同步包装器（向后兼容）。底层调用 delete_async()。"""
        return asyncio.run(self.delete_async(mem_id, sync_vector=sync_vector))

'''
    content = content.replace(old_delete_sync, '')

    # 9. delete_async -> delete
    content = content.replace('async def delete_async(self, mem_id: str, sync_vector: bool = True) -> bool:', 'async def delete(self, mem_id: str, sync_vector: bool = True) -> bool:')

    # 10. 改造 MemoryManager：def -> async def，store.xxx -> await store.xxx
    # add
    content = content.replace(
        '    def add(self, user_id: str, layer: str, content: dict, source: Union[MemorySource, str] = None, **kwargs) -> str:  # 定义添加记忆方法\n        """添加记忆（自动路由到对应用户存储）"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return store.add(layer=layer, content=content, source=source, **kwargs)  # 调用添加方法',
        '    async def add(self, user_id: str, layer: str, content: dict, source: Union[MemorySource, str] = None, **kwargs) -> str:  # 定义添加记忆方法\n        """添加记忆（自动路由到对应用户存储）"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return await store.add(layer=layer, content=content, source=source, **kwargs)  # 调用添加方法'
    )

    # add_memory
    content = content.replace(
        '    def add_memory(self, user_id: str, content: str, memory_type: str = "general",',
        '    async def add_memory(self, user_id: str, content: str, memory_type: str = "general",'
    )
    content = content.replace(
        '        # 调用add方法\n        return self.add(',
        '        # 调用add方法\n        return await self.add('
    )

    # query
    content = content.replace(
        '    def query(self, user_id: str, layer: Optional[str] = None, **kwargs) -> List[Dict]:  # 定义查询记忆方法\n        """查询记忆（自动路由到对应用户存储）"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return store.query(layer=layer, **kwargs)  # 调用查询方法',
        '    async def query(self, user_id: str, layer: Optional[str] = None, **kwargs) -> List[Dict]:  # 定义查询记忆方法\n        """查询记忆（自动路由到对应用户存储）"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return await store.query(layer=layer, **kwargs)  # 调用查询方法'
    )

    # update
    content = content.replace(
        '    def update(self, user_id: str, mem_id: str, updates: Dict) -> bool:  # 定义更新记忆方法\n        """更新记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return store.update(mem_id, updates)  # 调用更新方法',
        '    async def update(self, user_id: str, mem_id: str, updates: Dict) -> bool:  # 定义更新记忆方法\n        """更新记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return await store.update(mem_id, updates)  # 调用更新方法'
    )

    # delete
    content = content.replace(
        '    def delete(self, user_id: str, mem_id: str, sync_vector: bool = True) -> bool:  # 定义删除记忆方法\n        """删除记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return store.delete(mem_id, sync_vector=sync_vector)  # 调用删除方法',
        '    async def delete(self, user_id: str, mem_id: str, sync_vector: bool = True) -> bool:  # 定义删除记忆方法\n        """删除记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return await store.delete(mem_id, sync_vector=sync_vector)  # 调用删除方法'
    )

    # delete_memory
    content = content.replace(
        '    def delete_memory(self, user_id: str, mem_id: str) -> bool:  # 定义删除记忆方法（别名）',
        '    async def delete_memory(self, user_id: str, mem_id: str) -> bool:  # 定义删除记忆方法（别名）'
    )
    content = content.replace(
        '            return store.delete(mem_id, sync_vector=True)  # 调用删除方法\n        except Exception as e:  # 捕获异常',
        '            return await store.delete(mem_id, sync_vector=True)  # 调用删除方法\n        except Exception as e:  # 捕获异常'
    )

    # get_by_id
    content = content.replace(
        '    def get_by_id(self, user_id: str, mem_id: str) -> Optional[Dict]:  # 定义根据ID获取记忆方法\n        """根据ID获取记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return store.get_by_id(mem_id)  # 调用获取方法',
        '    async def get_by_id(self, user_id: str, mem_id: str) -> Optional[Dict]:  # 定义根据ID获取记忆方法\n        """根据ID获取记忆"""  # 方法文档字符串\n        store = self.get_user_store(user_id)  # 获取用户存储\n        return await store.get_by_id(mem_id)  # 调用获取方法'
    )

    # 11. 改造 Memory 类
    content = content.replace(
        '    def add(self, layer: str, mem_type: str, content: Any, context: Dict = None,',
        '    async def add(self, layer: str, mem_type: str, content: Any, context: Dict = None,'
    )
    content = content.replace(
        '        return self._get_manager().add(  # P0修复: 使用安全方法获取管理器',
        '        return await self._get_manager().add(  # P0修复: 使用安全方法获取管理器'
    )

    content = content.replace(
        '    def update(self, mem_id: str, **kwargs) -> bool:  # 定义更新方法',
        '    async def update(self, mem_id: str, **kwargs) -> bool:  # 定义更新方法'
    )
    content = content.replace(
        '        return self.add("evolve", "ai_autonomy", content, {"task_name": task_name}, rating=0)  # 调用添加方法',
        '        return await self.add("evolve", "ai_autonomy", content, {"task_name": task_name}, rating=0)  # 调用添加方法'
    )
    content = content.replace(
        '        return self.add("evolve", "event", content, {"task_name": task_name}, rating=0)  # 调用添加方法',
        '        return await self.add("evolve", "event", content, {"task_name": task_name}, rating=0)  # 调用添加方法'
    )
    content = content.replace(
        '        return self.add("evolve", "reflection", task_result, {',
        '        return await self.add("evolve", "reflection", task_result, {'
    )
    content = content.replace(
        '            mem_id = self.add(  # 调用添加方法',
        '            mem_id = await self.add(  # 调用添加方法'
    )

    content = content.replace(
        '    def delete(self, mem_id: str) -> bool:  # 定义删除方法',
        '    async def delete(self, mem_id: str) -> bool:  # 定义删除方法'
    )
    content = content.replace(
        '        return self._get_manager().delete(self._default_user_id, mem_id)',
        '        return await self._get_manager().delete(self._default_user_id, mem_id)'
    )

    with open('core/memory/memory.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print('[memory.py] 改造完成')
    import py_compile
    py_compile.compile('core/memory/memory.py', doraise=True)
    print('[memory.py] 语法检查通过')


def fix_memory_manager_py():
    with open('core/memory/memory_manager.py', encoding='utf-8') as f:
        content = f.read()

    # 找到所有调用 memory.add / memory.query / memory.delete 等的地方，加上 await
    # 同时把包含这些调用的函数改为 async def

    # 先把最顶层的 store_memory 改为 async
    # 这是一个简化版：把 def store_memory -> async def store_memory，并把内部的 memory.add 改为 await memory.add
    content = content.replace(
        '            mem_id = memory.add(  # 调用底层添加方法',
        '            mem_id = await memory.add(  # 调用底层添加方法'
    )

    # 把 store_memory 改为 async
    # 需要找到它的定义行
    content = content.replace(
        '    def store_memory(self,',
        '    async def store_memory(self,'
    )

    with open('core/memory/memory_manager.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print('[memory_manager.py] 改造完成')


def fix_execution_memory_py():
    with open('core/memory/execution_memory.py', encoding='utf-8') as f:
        content = f.read()

    content = content.replace(
        '        return store.add(record)',
        '        return await store.add(record)'
    )
    content = content.replace(
        '        return store.add_with_compensation(record)',
        '        return await store.add_with_compensation(record)'
    )

    with open('core/memory/execution_memory.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print('[execution_memory.py] 改造完成')


if __name__ == '__main__':
    fix_memory_py()
    fix_memory_manager_py()
    fix_execution_memory_py()
    print('\nPhase 1 完成')
