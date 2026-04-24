import os
from pathlib import Path

SKIP_EXTENSIONS = {
    '.lock', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
    '.woff', '.woff2', '.ttf', '.eot', '.map', '.min.js',
    '.zip', '.tar', '.gz', '.pdf', '.bin',
}

SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', 'dist', 'build',
    '.next', '.nuxt', 'coverage', '.nyc_output', 'vendor',
}

MAX_FILE_CHARS = 50_000   # Skip files larger than this (likely generated)
MAX_LINE_LENGTH = 500      # Skip minified files
TOTAL_CONTEXT_LIMIT = 90_000  # Soft cap on total chars sent to Bob


def load_repo(path: str) -> dict[str, str]:
    """Walk the repo and return {relative_path: content} for all readable files."""
    files: dict[str, str] = {}
    root = Path(path)

    if not root.exists():
        raise FileNotFoundError(f"Repo path not found: {path}")

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file():
            continue

        # Skip blocked directories
        if any(skip in fpath.parts for skip in SKIP_DIRS):
            continue

        # Skip blocked extensions
        if any(str(fpath).endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        # Skip empty and oversized files
        if not content.strip() or len(content) > MAX_FILE_CHARS:
            continue

        # Skip minified files (very long lines = minified)
        lines = content.splitlines()
        if lines and max((len(l) for l in lines), default=0) > MAX_LINE_LENGTH:
            continue

        rel_path = str(fpath.relative_to(root))
        files[rel_path] = content

    return files


def build_file_tree(paths: list[str]) -> str:
    """Render a tree-like structure from a list of file paths."""
    tree_lines: list[str] = []
    prev_parts: list[str] = []

    for path in sorted(paths):
        parts = path.split(os.sep) if os.sep in path else path.split('/')
        # Find common depth
        common = 0
        for a, b in zip(prev_parts, parts[:-1]):
            if a == b:
                common += 1
            else:
                break

        for i, part in enumerate(parts[:-1]):
            if i >= len(prev_parts) or prev_parts[i] != part:
                indent = "  " * i
                tree_lines.append(f"{indent}📁 {part}/")

        indent = "  " * (len(parts) - 1)
        tree_lines.append(f"{indent}📄 {parts[-1]}")
        prev_parts = parts

    return "\n".join(tree_lines)


def prioritize_files(
    all_files: dict[str, str],
    changed_files: list[str],
    symbols: list[str],
) -> list[str]:
    """
    Return file paths ordered by relevance to the changed symbols:
    1. Changed files themselves
    2. Files that import or reference changed symbols
    3. Test files
    4. Everything else
    """
    priority_1: list[str] = []  # directly changed
    priority_2: list[str] = []  # imports changed symbols
    priority_3: list[str] = []  # test files
    priority_4: list[str] = []  # everything else

    # Normalize changed file paths for matching
    changed_set = set(changed_files)
    changed_basenames = [
        os.path.splitext(os.path.basename(f))[0]
        for f in changed_files
    ]

    for path, content in all_files.items():
        if path in changed_set:
            priority_1.append(path)
            continue

        is_test = any(t in path for t in ['__tests__', '.test.', '.spec.', 'test/'])
        references_change = (
            any(basename in content for basename in changed_basenames) or
            any(f"'{sym}'" in content or f'"{sym}"' in content or f' {sym}(' in content
                for sym in symbols)
        )

        if references_change:
            priority_2.append(path)
        elif is_test:
            priority_3.append(path)
        else:
            priority_4.append(path)

    return priority_1 + priority_2 + priority_3 + priority_4


def get_context_bundle(
    all_files: dict[str, str],
    changed_files: list[str],
    symbols: list[str],
) -> dict[str, str]:
    """
    Return a subset of files within the context limit, priority-ordered.
    """
    ordered_paths = prioritize_files(all_files, changed_files, symbols)
    bundle: dict[str, str] = {}
    total_chars = 0

    for path in ordered_paths:
        content = all_files[path]
        if total_chars + len(content) > TOTAL_CONTEXT_LIMIT:
            break
        bundle[path] = content
        total_chars += len(content)

    return bundle
