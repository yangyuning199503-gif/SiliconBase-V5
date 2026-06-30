import json

with open('exception_audit_raw.json', encoding='utf-8') as f:
    data = json.load(f)

from collections import Counter

sev_counts = Counter(v['severity'] for v in data)
type_counts = Counter(v['type'] for v in data)

report_lines = []
report_lines.append('# Exception Handling Audit Report')
report_lines.append(r'**Project:** E:\SiliconBase_V5\SiliconBase_V5')
report_lines.append('**Date:** 2026-06-08')
report_lines.append('')
report_lines.append('## Summary')
report_lines.append('')
report_lines.append(f'- **Total try/except blocks analyzed:** {len(data)}')
report_lines.append(f'- **Bare except: clauses:** {type_counts["bare_except"]}')
report_lines.append(f'- **except Exception: / except Exception as e: clauses:** {type_counts["except_exception"]}')
report_lines.append('')
report_lines.append('### Severity Breakdown')
report_lines.append('')
report_lines.append('| Severity | Count | Description |')
report_lines.append('|----------|-------|-------------|')
report_lines.append(f'| **CRITICAL** | {sev_counts.get("CRITICAL", 0)} | Bare/except + silent ignore (pass, empty block, or no log/no raise) |')
report_lines.append(f'| **HIGH** | {sev_counts.get("HIGH", 0)} | except Exception + silent ignore (returns None/False/empty, pass without log, no action) |')
report_lines.append(f'| **MEDIUM** | {sev_counts.get("MEDIUM", 0)} | Inadequate logging (only debug level, single log line without further handling) |')
report_lines.append(f'| **LOW** | {sev_counts.get("LOW", 0)} | Logs but does not re-raise (acceptable in some contexts) |')
report_lines.append(f'| **OK** | {sev_counts.get("OK", 0)} | Re-raises or otherwise adequate handling |')
report_lines.append('')
report_lines.append(f'**Total Violations (CRITICAL + HIGH + MEDIUM):** {sev_counts.get("CRITICAL", 0) + sev_counts.get("HIGH", 0) + sev_counts.get("MEDIUM", 0)}')
report_lines.append('')

def emit_section(title, severity_filter, limit=100):
    report_lines.append(f'## {title}')
    report_lines.append('')
    subset = [v for v in data if v['severity'] == severity_filter]
    report_lines.append(f'Total: **{len(subset)}** violations')
    report_lines.append('')
    from collections import defaultdict
    by_file = defaultdict(list)
    for v in subset:
        by_file[v['file']].append(v)
    shown = 0
    for filepath in sorted(by_file.keys()):
        if shown >= limit:
            break
        vs = by_file[filepath]
        report_lines.append(f'### {filepath}')
        report_lines.append('')
        for v in vs:
            if shown >= limit:
                break
            shown += 1
            report_lines.append(f"**Line {v['line']}** — `{v['except_line'].strip()}` — *{v['reason']}*")
            if v['try_line']:
                report_lines.append(f"> try: `{v['try_line'].strip()}`")
            if v['body']:
                report_lines.append('```python')
                for _ln, txt in v['body']:
                    report_lines.append(txt)
                report_lines.append('```')
            report_lines.append('')
    if shown < len(subset):
        report_lines.append(f"*(... and {len(subset) - shown} more in this category)*")
        report_lines.append('')

emit_section('CRITICAL Violations (bare except + silent)', 'CRITICAL', 100)
emit_section('HIGH Violations (except Exception + silent)', 'HIGH', 100)
emit_section('MEDIUM Violations (inadequate logging)', 'MEDIUM', 100)

report_lines.append('## Recommendations')
report_lines.append('')
report_lines.append('1. **CRITICAL fixes first:** Replace all bare `except:` with specific exception types. Never use bare except in production code.')
report_lines.append('2. **HIGH fixes:** Ensure every `except Exception` block either re-raises, logs at ERROR/WARNING level, or returns a meaningful error response. Do not silently return None/False/empty collections.')
report_lines.append('3. **MEDIUM fixes:** Upgrade `logger.debug()` calls inside except blocks to at least `logger.warning()` or `logger.error()`. If the exception is truly expected and harmless, document why with a comment.')
report_lines.append('4. **General:** Use `except Exception as e:` and always log `str(e)` or use `logger.exception()` to capture traceback context.')
report_lines.append('')

with open('EXCEPTION_HANDLING_AUDIT_REPORT.md', 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))

print('Report written to EXCEPTION_HANDLING_AUDIT_REPORT.md')
