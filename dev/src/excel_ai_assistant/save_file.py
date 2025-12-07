# excel_app.py

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    status,
)
from fastapi.concurrency import run_in_threadpool
from uuid import uuid4

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Excel Upload Service",
    version="1.0.0",
)

# ---- Config (environment-override friendly) ----
UPLOAD_ROOT = Path(os.getenv("EXCEL_UPLOAD_ROOT", "excel_uploads")).resolve()
MAX_UPLOAD_BYTES = int(
    os.getenv("EXCEL_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
)  # 10 MB default
CHUNK_SIZE = 1024 * 1024  # 1 MB per chunk

ALLOWED_EXCEL_TYPES: Dict[str, str] = {
    # Modern Excel (.xlsx)
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    # Legacy Excel (.xls)
    "application/vnd.ms-excel": ".xls",
    # Excel-like CSV (optional, can be removed if you want strictly Excel)
    "text/csv": ".csv",
}


def ensure_upload_dir() -> None:
    """
    Ensure the upload root directory exists and is writable.

    This is executed at application startup to fail fast if the target
    directory cannot be used.
    """
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    if not os.access(UPLOAD_ROOT, os.W_OK):
        raise RuntimeError(f"Upload directory {UPLOAD_ROOT} is not writable")


def generate_excel_path(content_type: str, allowed_types: Dict[str, str]) -> Path:
    """
    Generate a safe, unique path for the uploaded Excel file.

    Uses a UUID and sharded subdirectories to avoid directory hot-spots.

    Parameters
    ----------
    content_type:
        The content type reported by the client for the uploaded file.
    allowed_types:
        Mapping of allowed content types to file extensions.

    Returns
    -------
    Path
        The fully qualified file path where the Excel file should be stored.

    Raises
    ------
    HTTPException
        If the content type is not allowed.
    """
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported Excel file type",
        )

    extension = allowed_types[content_type]
    uid = uuid4().hex

    # Example sharding: excel_uploads/ab/cd/abcdef...xlsx
    shard1, shard2 = uid[:2], uid[2:4]
    dir_path = UPLOAD_ROOT / shard1 / shard2
    dir_path.mkdir(parents=True, exist_ok=True)

    return dir_path / f"{uid}{extension}"


def _save_upload_file_streaming(
    upload_file: UploadFile,
    destination: Path,
    max_bytes: int,
) -> None:
    """
    Blocking implementation that streams an UploadFile to disk in chunks.

    Intended to be run in a threadpool from an async path operation.

    Parameters
    ----------
    upload_file:
        The incoming uploaded file object from FastAPI.
    destination:
        The absolute path where the file should be written.
    max_bytes:
        Maximum allowed size in bytes. A 413 error is raised if exceeded.

    Raises
    ------
    HTTPException
        For validation errors, size violations, or save failures.
    """
    total_bytes = 0

    try:
        with destination.open("wb") as out_file:
            while True:
                chunk = upload_file.file.read(CHUNK_SIZE)
                if not chunk:
                    break

                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    # Remove partial file to avoid leaving junk on disk.
                    try:
                        destination.unlink(missing_ok=True)
                    except Exception:
                        logger.exception(
                            "Failed to remove oversized partial Excel upload: %s",
                            destination,
                        )

                    raise HTTPException(
                        status_code=413,
                        detail=f"Excel file too large (max {max_bytes} bytes)",
                    )

                out_file.write(chunk)

    except HTTPException:
        # Re-raise FastAPI HTTP errors directly.
        raise
    except Exception as exc:
        # Log and convert to generic 500 for the client.
        logger.exception("Error while saving uploaded Excel file: %s", exc)
        try:
            destination.unlink(missing_ok=True)
        except Exception:
            logger.exception(
                "Failed to cleanup destination file after error: %s",
                destination,
            )
        raise HTTPException(
            status_code=500,
            detail="Failed to save Excel file",
        )


def _delete_saved_excel(path: Path) -> None:
    """
    Delete a previously saved Excel file and attempt to clean up empty
    sharded directories above it.

    - Does not raise if the file does not exist.
    - Attempts to delete parent directories up to UPLOAD_ROOT when empty.

    Parameters
    ----------
    path:
        Absolute or relative path to the Excel file to be deleted.

    Raises
    ------
    HTTPException
        If the path is invalid, outside of UPLOAD_ROOT, or deletion fails.
    """
    try:
        target_path = path.resolve()
    except Exception as exc:
        logger.exception("Invalid Excel path %r: %s", path, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Excel path",
        )

    # Security: ensure the file is actually under UPLOAD_ROOT
    try:
        target_path.relative_to(UPLOAD_ROOT)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Excel path",
        )

    # 1) Delete the file (silently if it does not exist)
    try:
        target_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.exception("Failed to delete Excel file %s: %s", target_path, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete Excel file",
        )

    # 2) Clean up empty sharded directories up to UPLOAD_ROOT
    for parent in target_path.parents:
        if parent == UPLOAD_ROOT:
            break
        try:
            parent.rmdir()  # succeeds only if directory is empty
        except OSError:
            # Directory not empty or normal issue -> stop silently
            break
        except Exception as exc:
            logger.exception("Failed to cleanup directory %s: %s", parent, exc)
            break