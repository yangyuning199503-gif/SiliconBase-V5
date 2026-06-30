#!/usr/bin/env python3
import re

with open('core/session/session_integration.py', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 SessionIntegration 类中所有方法边界
methods = []
in_class = False
class_indent = 4

for i, line in enumerate(lines):
    if 'class SessionIntegration:' in line:
        in_class = True
        continue
    if not in_class:
        continue
    # 匹配类级方法（4空格缩进）
    m = re.match(r'    (async )?def ([a-zA-Z_][a-zA-Z0-9_]*)\(', line)
    if m:
        methods.append((i, m.group(1) is not None, m.group(2)))

print("Methods found:")
for idx, is_async, name in methods:
    print(f"  line {idx+1}: {'async' if is_async else 'sync'} {name}")

# 策略：删除 sync 方法，保留 async 方法（去掉 _async 后缀）
# 方法范围：从方法定义行到下一个同级方法/类结束/文件结束
method_ranges = []
for i, (idx, is_async, name) in enumerate(methods):
    start = idx
    if i + 1 < len(methods):
        end = methods[i+1][0]
    else:
        # 到类结束或文件结束
        end = len(lines)
        # 尝试找到下一个非缩进行（类结束）
        for j in range(start+1, len(lines)):
            if lines[j].strip() and not lines[j].startswith(' '):
                end = j
                break
            if lines[j].startswith('    #') or lines[j].startswith('    @'):
                # 装饰器或注释，继续
                pass
    method_ranges.append((start, end, is_async, name))

# 确定要删除的范围：sync 方法 + store_and_trigger_ai_response_async（与 store_and_trigger_ai_response 合并）
delete_ranges = []
keep_lines = set()
for start, end, is_async, name in method_ranges:
    if not is_async:
        delete_ranges.append((start, end))
        print(f"DELETE sync {name} (lines {start+1}-{end})")
    elif name == 'store_and_trigger_ai_response_async':
        # 删除这个，保留 store_and_trigger_ai_response 并改为 async
        delete_ranges.append((start, end))
        print(f"DELETE async {name} (duplicate, lines {start+1}-{end})")
    else:
        print(f"KEEP async {name} (lines {start+1}-{end})")

# 还要删除类前面的同步/异步双入口注释中的 "同步/异步双入口" 字样
# 以及 docstring 中的同步描述

# 先标记删除行
for start, end in delete_ranges:
    for i in range(start, end):
        keep_lines.add(i)

# 处理保留的行：去掉 _async 后缀
new_lines = []
for i, line in enumerate(lines):
    if i in keep_lines:
        continue
    # 去掉方法名中的 _async 后缀
    line = re.sub(r'def ([a-zA-Z_][a-zA-Z0-9_]*)_async\(', lambda m: f'def {m.group(1)}(', line)
    new_lines.append(line)

with open('core/session/session_integration.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Done. Original: {len(lines)}, New: {len(new_lines)}")
