import re
from models import DiffResult

# Patterns to extract changed function/class/const names from diff lines
SYMBOL_PATTERNS = [
    r'^[+-].*\bfunction\s+(\w+)',
    r'^[+-].*\bconst\s+(\w+)\s*=\s*(?:async\s*)?\(',
    r'^[+-].*\bclass\s+(\w+)',
    r'^[+-].*\bdef\s+(\w+)',
    r'^[+-].*\basync\s+function\s+(\w+)',
    r'^[+-].*\bmodule\.exports\s*=\s*\{([^}]+)\}',
]


def parse_diff(diff_text: str) -> DiffResult:
    result = DiffResult(raw_diff=diff_text)

    for line in diff_text.splitlines():
        # Extract changed file paths
        if line.startswith("--- ") or line.startswith("+++ "):
            raw_path = line[4:].strip()
            # Strip git a/ b/ prefixes
            path = re.sub(r'^[ab]/', '', raw_path)
            if path != "/dev/null" and path not in result.changed_files:
                result.changed_files.append(path)
            continue

        # Extract changed symbols
        for pattern in SYMBOL_PATTERNS:
            m = re.search(pattern, line)
            if m:
                # Handle module.exports = { fn1, fn2 } pattern
                if 'module.exports' in line and m.group(1):
                    names = [n.strip() for n in m.group(1).split(',')]
                    for name in names:
                        name = name.split(':')[0].strip()
                        if name and name not in result.symbols:
                            result.symbols.append(name)
                else:
                    name = m.group(1)
                    if name and name not in result.symbols:
                        result.symbols.append(name)
                break

    # Deduplicate changed_files (--- and +++ both appear)
    seen = set()
    unique = []
    for f in result.changed_files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    result.changed_files = unique

    return result
