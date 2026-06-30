import re

with open('core/session/session_manager.py', encoding='utf-8') as f:
    content = f.read()

# Remove psycopg2 imports
content = content.replace('import psycopg2\n', '')
content = content.replace('from psycopg2.extras import RealDictCursor\n', '')
content = content.replace('from core.db.connection_pool import get_db_connection\n', '')

# Remove sync create_session through update_message_memory_id
pattern1 = r'    def create_session\(.*?\n        raise SessionCreateError\(f"创建会话时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern1, '\n', content, flags=re.DOTALL, count=1)

# Remove sync get_session
pattern2 = r'    def get_session\(.*?\n        raise SessionManagerError\(f"获取会话时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern2, '\n', content, flags=re.DOTALL, count=1)

# Remove sync list_sessions
pattern3 = r'    def list_sessions\(.*?\n        raise SessionManagerError\(f"获取会话列表时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern3, '\n', content, flags=re.DOTALL, count=1)

# Remove sync update_session
pattern4 = r'    def update_session\(.*?\n        raise SessionUpdateError\(f"更新会话时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern4, '\n', content, flags=re.DOTALL, count=1)

# Remove sync delete_session
pattern5 = r'    def delete_session\(.*?\n        raise SessionDeleteError\(f"删除会话时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern5, '\n', content, flags=re.DOTALL, count=1)

# Remove sync add_message
pattern6 = r'    def add_message\(.*?\n        raise MessageAddError\(f"添加消息时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern6, '\n', content, flags=re.DOTALL, count=1)

# Remove sync update_message_memory_id
pattern7 = r'    def update_message_memory_id\(.*?\n        raise SessionManagerError\(f"更新消息memory_id时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern7, '\n', content, flags=re.DOTALL, count=1)

# Remove sync get_messages
pattern8 = r'    def get_messages\(.*?\n        raise SessionManagerError\(f"获取消息时发生未知错误: \{e\}"\) from e\n'
content = re.sub(pattern8, '\n', content, flags=re.DOTALL, count=1)

# Rename _async methods to standard
for name in ['create_session', 'get_session', 'add_message', 'get_messages',
             'list_sessions', 'update_session', 'delete_session', 'update_message_memory_id']:
    content = content.replace(f'async def {name}_async(', f'async def {name}(')

# Fix log messages
content = content.replace('会话异步创建成功', '会话创建成功')
content = content.replace('消息异步添加成功', '消息添加成功')
content = content.replace('异步删除会话成功', '删除会话成功')
content = content.replace('异步获取会话失败', '获取会话失败')
content = content.replace('异步获取消息失败', '获取消息失败')
content = content.replace('异步获取会话列表失败', '获取会话列表失败')
content = content.replace('异步更新会话失败', '更新会话失败')
content = content.replace('异步添加消息失败', '添加消息失败')
content = content.replace('异步更新消息memory_id失败', '更新消息memory_id失败')
content = content.replace('异步更新消息memory_id成功', '更新消息memory_id成功')
content = content.replace('消息memory_id异步更新成功', '消息memory_id更新成功')
content = content.replace('异步创建会话失败', '创建会话失败')
content = content.replace('异步获取会话失败', '获取会话失败')
content = content.replace('异步获取消息时发生错误', '获取消息时发生错误')
content = content.replace('异步获取会话列表时发生错误', '获取会话列表时发生错误')
content = content.replace('异步更新会话时发生错误', '更新会话时发生错误')
content = content.replace('异步删除会话时发生错误', '删除会话时发生错误')
content = content.replace('异步创建会话失败', '创建会话失败')
content = content.replace('异步添加消息时发生错误', '添加消息时发生错误')
content = content.replace('异步更新消息memory_id时发生错误', '更新消息memory_id时发生错误')

# Update docstrings
content = content.replace('"""异步创建新会话"""', '"""创建新会话"""')
content = content.replace('"""异步获取单个会话"""', '"""获取单个会话"""')
content = content.replace('"""异步添加消息到会话"""', '"""添加消息到会话"""')
content = content.replace('"""异步分页获取会话消息"""', '"""分页获取会话消息"""')
content = content.replace('"""异步分页获取用户会话列表"""', '"""分页获取用户会话列表"""')
content = content.replace('"""异步更新会话信息"""', '"""更新会话信息"""')
content = content.replace('"""异步删除会话（级联删除消息）"""', '"""删除会话（级联删除消息）"""')
content = content.replace('"""异步更新消息关联的记忆ID（使用 asyncpg）"""', '"""更新消息关联的记忆ID"""')

# Update module-level convenience functions
replacements = [
    ('def create_session(', 'async def create_session('),
    ('def get_session(session_id:', 'async def get_session(session_id:'),
    ('def list_sessions(', 'async def list_sessions('),
    ('def update_session(session_id:', 'async def update_session(session_id:'),
    ('def delete_session(session_id:', 'async def delete_session(session_id:'),
    ('def add_message(', 'async def add_message('),
    ('def get_messages(', 'async def get_messages('),
    ('def update_message_memory_id(message_id:', 'async def update_message_memory_id(message_id:'),
]

for old, new in replacements:
    content = content.replace(old, new, 1)

# Add await to convenience function bodies
content = content.replace(
    'return get_session_manager().create_session(user_id, title, mode, initial_context)',
    'return await get_session_manager().create_session(user_id, title, mode, initial_context)'
)
content = content.replace(
    'return get_session_manager().get_session(session_id)',
    'return await get_session_manager().get_session(session_id)'
)
content = content.replace(
    'return get_session_manager().list_sessions(user_id, limit, offset, status)',
    'return await get_session_manager().list_sessions(user_id, limit, offset, status)'
)
content = content.replace(
    'return get_session_manager().update_session(session_id, updates)',
    'return await get_session_manager().update_session(session_id, updates)'
)
content = content.replace(
    'return get_session_manager().delete_session(session_id)',
    'return await get_session_manager().delete_session(session_id)'
)
content = content.replace(
    'return get_session_manager().add_message(session_id, role, content, **kwargs)',
    'return await get_session_manager().add_message(session_id, role, content, **kwargs)'
)
content = content.replace(
    'return get_session_manager().get_messages(session_id, limit, before_id)',
    'return await get_session_manager().get_messages(session_id, limit, before_id)'
)
content = content.replace(
    'return get_session_manager().update_message_memory_id(message_id, memory_id)',
    'return await get_session_manager().update_message_memory_id(message_id, memory_id)'
)

# Replace __main__ test with async version
old_main_start = 'if __name__ == "__main__":'
old_main_idx = content.find(old_main_start)
if old_main_idx != -1:
    new_main = '''async def _run_tests():
    import sys
    print("=" * 60)
    print("SessionManager 单元测试")
    print("=" * 60)
    TEST_USER_ID = "test_user_001"
    manager = SessionManager()
    test_session_id = None
    try:
        print("\\n[测试1] 创建会话...")
        session = await manager.create_session(
            user_id=TEST_USER_ID, title="测试会话", mode="daily", initial_context={"test": True}
        )
        test_session_id = session.id
        print(f"✓ 会话创建成功: {session.id}")
        print("\\n[测试2] 添加消息...")
        msg1_id = await manager.add_message(
            session_id=test_session_id, role="user", content="你好，这是一个测试消息", metadata={"source": "test"}
        )
        print(f"✓ 消息1添加成功: {msg1_id}")
        msg2_id = await manager.add_message(
            session_id=test_session_id, role="assistant", content="收到，测试消息已记录"
        )
        print(f"✓ 消息2添加成功: {msg2_id}")
        print("\\n[测试3] 获取会话...")
        session = await manager.get_session(test_session_id)
        print(f"✓ 会话获取成功, message_count: {session.message_count}")
        print("\\n[测试4] 获取消息...")
        has_more, next_cursor, messages = await manager.get_messages(session_id=test_session_id, limit=10)
        print(f"✓ 消息获取成功, count: {len(messages)}")
        print("\\n[测试5] 更新会话...")
        updated = await manager.update_session(session_id=test_session_id, updates={"title": "更新后的标题", "status": "archived"})
        print(f"✓ 会话更新成功, title: {updated.title}")
        print("\\n[测试6] 获取会话列表...")
        total, sessions = await manager.list_sessions(user_id=TEST_USER_ID, limit=10)
        print(f"✓ 会话列表获取成功, total: {total}")
        print("\\n[测试7] 删除会话...")
        deleted_count = await manager.delete_session(test_session_id)
        print(f"✓ 会话删除成功, deleted_messages: {deleted_count}")
        print("\\n[测试8] 验证删除...")
        deleted_session = await manager.get_session(test_session_id)
        if deleted_session is None:
            print("✓ 会话已正确删除")
        else:
            print(f"✗ 会话仍然存在")
            sys.exit(1)
        print("\\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        if test_session_id:
            try:
                await manager.delete_session(test_session_id)
                print(f"  (已清理测试会话: {test_session_id})")
            except Exception:
                pass

if __name__ == "__main__":
    import asyncio
    asyncio.run(_run_tests())
'''
    content = content[:old_main_idx] + new_main

with open('core/session/session_manager.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('session_manager.py rewritten successfully')
