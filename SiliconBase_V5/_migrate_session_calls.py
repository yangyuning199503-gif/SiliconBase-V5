import ast
import os

TARGET_METHODS = {
    'create_session', 'get_session', 'list_sessions', 'update_session',
    'delete_session', 'add_message', 'get_messages', 'update_message_memory_id'
}

def find_calls_in_async(source):
    tree = ast.parse(source)
    lines = source.split('\n')
    edits = []

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    method_name = None
                    if isinstance(func, ast.Attribute) and func.attr in TARGET_METHODS:
                        method_name = func.attr
                    elif isinstance(func, ast.Name) and func.id in TARGET_METHODS:
                        method_name = func.id

                    if method_name:
                        line_idx = sub.lineno - 1
                        col = sub.col_offset
                        line = lines[line_idx]
                        # Check if already awaited
                        before = line[:col].strip()
                        if before.endswith('await') or before.endswith('await '):
                            continue
                        # Find the start of the call expression
                        # We need to insert 'await ' before the expression
                        # Simple approach: insert at col
                        edits.append((line_idx, col, method_name))

    # Apply edits from right to left per line
    edits_by_line = {}
    for line_idx, col, name in edits:
        edits_by_line.setdefault(line_idx, []).append((col, name))

    for line_idx, cols in edits_by_line.items():
        line = lines[line_idx]
        new_line = line
        for col, _name in sorted(cols, reverse=True):
            new_line = new_line[:col] + 'await ' + new_line[col:]
        lines[line_idx] = new_line

    return '\n'.join(lines)


def process_file(path):
    with open(path, encoding='utf-8') as f:
        source = f.read()

    # Quick check if file contains any target patterns
    has_target = False
    for m in TARGET_METHODS:
        if m + '(' in source or '.' + m + '(' in source:
            has_target = True
            break
    if not has_target:
        return 0

    try:
        new_source = find_calls_in_async(source)
    except SyntaxError:
        print(f'Syntax error in {path}, skipping')
        return 0

    if new_source != source:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_source)
        # Count changes
        count = sum(1 for a, b in zip(source.split('\n'), new_source.split('\n'), strict=False) if a != b)
        return count
    return 0


total_changes = 0
changed_files = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ('.venv', '__pycache__', '.pytest_cache', '.mypy_cache', 'archive', 'backups', 'tmp_test', 'data')]
    for f in files:
        if not f.endswith('.py'):
            continue
        path = os.path.join(root, f)
        # Skip session_manager itself
        if 'session_manager.py' in path:
            continue
        changes = process_file(path)
        if changes:
            total_changes += changes
            changed_files.append(path)

print(f'Modified {len(changed_files)} files, {total_changes} lines changed')
for p in changed_files:
    print(f'  {p}')
