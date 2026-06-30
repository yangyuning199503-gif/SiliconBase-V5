import os
import re

# Files to fix
test_files = [
    'tests/test_agent_loop_session_storage.py',
    'tests/test_memory_session_association.py',
]

# Pattern: session_manager.xxx(...)
def fix_file(path):
    with open(path, encoding='utf-8') as f:
        content = f.read()

    # Replace session_manager.xxx( with asyncio.run(session_manager.xxx(...))
    # But be careful not to double-wrap
    methods = ['create_session', 'get_session', 'add_message', 'get_messages',
               'list_sessions', 'update_session', 'delete_session', 'update_message_memory_id']

    for m in methods:
        # Wrap simple assignments
        content = re.sub(
            rf'([\w_]+)\s*=\s*session_manager\.{m}\(([^)]+)\)',
            rf'import asyncio\n            \1 = asyncio.run(session_manager.{m}(\2))',
            content
        )
        # Wrap standalone calls without assignment
        content = re.sub(
            rf'(?<![\w.])session_manager\.{m}\(([^)]+)\)',
            rf'import asyncio\n            asyncio.run(session_manager.{m}(\1))',
            content
        )

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Fixed {path}')

for f in test_files:
    if os.path.exists(f):
        fix_file(f)
    else:
        print(f'Not found: {f}')
