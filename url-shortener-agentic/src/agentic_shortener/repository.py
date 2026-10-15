"""Bounded, secret-aware repository snapshotting for brownfield reasoning."""

import hashlib
import os
import re
from pathlib import Path

from .config import ALLOWED_REPOSITORY_ROOTS


SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "data", "artifacts",
             "dist", "build", ".mypy_cache", ".ruff_cache"}
TEXT_SUFFIXES = {".py", ".md", ".rst", ".toml", ".ini", ".cfg", ".json", ".yaml", ".yml",
                 ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".cs", ".rs", ".sql", ".sh",
                 ".ps1", ".html", ".css"}
SECRET_ASSIGNMENT = re.compile(
    r"(?im)(\b(?:[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


class RepositoryScanner:
    def __init__(self, allowed_roots=ALLOWED_REPOSITORY_ROOTS, max_files=120,
                 max_file_bytes=128_000, max_total_chars=120_000, max_file_chars=14_000):
        self.allowed_roots = tuple(Path(root).expanduser().resolve() for root in allowed_roots)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes
        self.max_total_chars = max_total_chars
        self.max_file_chars = max_file_chars

    def snapshot(self, requested_root: str | Path) -> dict:
        root = Path(requested_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository_path must point to a directory")
        if not any(root == allowed or allowed in root.parents for allowed in self.allowed_roots):
            raise ValueError("repository_path is outside configured ALLOWED_REPOSITORY_ROOTS")
        files = []
        total_chars = 0
        truncated = False
        for directory, subdirs, filenames in os.walk(root, followlinks=False):
            subdirs[:] = sorted(name for name in subdirs
                                if name not in SKIP_DIRS and not (Path(directory) / name).is_symlink())
            for filename in sorted(filenames):
                path = Path(directory) / filename
                lower_name = filename.lower()
                if path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                if lower_name.startswith(".env") or any(tag in lower_name for tag in
                                                         ("secret", "credential", "id_rsa", "private_key")):
                    continue
                try:
                    stat = path.stat()
                    if stat.st_size > self.max_file_bytes:
                        continue
                    raw = path.read_bytes()
                    original = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                content = SECRET_ASSIGNMENT.sub(r"\1'[REDACTED]'", original)
                file_truncated = len(content) > self.max_file_chars
                content = content[:self.max_file_chars]
                remaining = self.max_total_chars - total_chars
                if remaining <= 0 or len(files) >= self.max_files:
                    truncated = True
                    break
                if len(content) > remaining:
                    content = content[:remaining]
                    file_truncated = True
                total_chars += len(content)
                files.append({"path": path.relative_to(root).as_posix(), "sha256": digest,
                              "content": content, "truncated": file_truncated})
                truncated |= file_truncated
            if truncated and (len(files) >= self.max_files or total_chars >= self.max_total_chars):
                break
        return {"root": str(root), "file_count": len(files), "total_chars": total_chars,
                "truncated": truncated, "files": files}
