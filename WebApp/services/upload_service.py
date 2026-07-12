"""Upload and local path helpers for the WebApp.

These helpers are intentionally framework-light so route handlers can keep
their response shapes while path safety stays centralized.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from werkzeug.utils import secure_filename


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_existing_inside(path_value: str, root: Path, require_dir: bool = False) -> Path:
    if not path_value:
        raise FileNotFoundError("Path not provided")
    resolved = Path(path_value).resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("Path is outside the WebApp upload directory") from exc
    if not resolved.exists():
        raise FileNotFoundError("Path not found")
    if require_dir and not resolved.is_dir():
        raise ValueError("Path is not a folder")
    return resolved


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def pdf_relative_name(path: Path, folder: Path) -> str:
    return path.resolve().relative_to(folder.resolve()).as_posix()


def discover_pdf_files(folder: Path, include_subfolders: bool = False) -> list[Path]:
    finder = folder.rglob if include_subfolders else folder.glob
    return sorted(
        (p for p in finder("*.pdf") if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: pdf_relative_name(p, folder).lower(),
    )


def resolve_pdf_file(folder: Path, filename: str) -> Path:
    if not filename:
        raise ValueError("Missing filename")
    target = (folder / filename).resolve()
    target.relative_to(folder.resolve())
    if target.suffix.lower() != ".pdf":
        raise ValueError("Invalid filename")
    return target


def validate_upload_filename(filename: str, allowed_exts: set[str]) -> tuple[str, str]:
    original = (filename or "").strip()
    if not original:
        raise ValueError("Empty filename")
    if "/" in original or "\\" in original or original in {".", ".."}:
        raise ValueError("Invalid filename")

    safe_name = secure_filename(original)
    if not safe_name or safe_name in {".", ".."}:
        raise ValueError("Invalid filename")

    ext = Path(safe_name).suffix.lower()
    if ext not in allowed_exts:
        raise ValueError(f"Unsupported format: {ext}")
    return original, ext


def save_uploaded_file(file_storage, folder: Path, allowed_exts: set[str], max_size: int) -> dict:
    original, ext = validate_upload_filename(file_storage.filename, allowed_exts)
    folder.mkdir(parents=True, exist_ok=True)
    server_filename = f"{uuid.uuid4().hex}{ext}"
    dest = (folder / server_filename).resolve()
    if not is_relative_to(dest, folder):
        raise ValueError("Invalid upload destination")

    file_storage.save(str(dest))
    size = dest.stat().st_size
    if size > max_size:
        dest.unlink(missing_ok=True)
        raise ValueError(f"File is too large; limit is {max_size // (1024 * 1024)} MB")

    return {
        "path": str(dest),
        "filename": server_filename,
        "original_filename": original,
        "size": size,
    }
