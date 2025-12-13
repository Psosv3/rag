# app.py
import os
import logging
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, UploadFile, File, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from uuid import uuid4

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI()

# ---- Config (environment-override friendly) ----
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "uploads")).resolve()
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))  # 10 MB default
CHUNK_SIZE = 1024 * 1024  # 1 MB per chunk

ALLOWED_IMAGE_TYPES: Dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def ensure_upload_dir() -> None:
    """
    Ensure the upload root directory exists and is writable.
    Called once at import time for simplicity.
    """
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    if not os.access(UPLOAD_ROOT, os.W_OK):
        raise RuntimeError(f"Upload directory {UPLOAD_ROOT} is not writable")

# ensure_upload_dir()

def generate_image_path(content_type: str, ALLOWED_IMAGE_TYPES: dict) -> Path:
    """
    Generate a safe, unique path for the uploaded image.
    Uses a UUID and sharded subdirectories to avoid directory hot-spots.
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image type",
        )

    extension = ALLOWED_IMAGE_TYPES[content_type]
    uid = uuid4().hex

    # Example sharding: uploads/ab/cd/abcdef...jpg
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

    Raises HTTPException on size limit violations.
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
                            "Failed to remove oversized partial upload: %s",
                            destination,
                        )

                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Image too large (max {max_bytes} bytes)",
                    )

                out_file.write(chunk)

    except HTTPException:
        # Re-raise FastAPI HTTP errors directly.
        raise
    except Exception as exc:
        # Log and convert to generic 500 for the client.
        logger.exception("Error while saving uploaded image: %s", exc)
        try:
            destination.unlink(missing_ok=True)
        except Exception:
            logger.exception(
                "Failed to cleanup destination file after error: %s", destination
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save image",
        )



def _delete_saved_image(path: Path) -> None:
    """
    Supprime un fichier d'image précédemment sauvegardé et,
    si possible, nettoie les répertoires shardés vides au-dessus.

    - Ne lève pas d'erreur si le fichier n'existe pas.
    - Tente de supprimer les dossiers parents vides jusqu'à UPLOAD_ROOT.
    """

    try:
        target_path = path.resolve()
    except Exception as exc:
        logger.exception("Invalid image path %r: %s", path, exc)
        raise HTTPException(status_code=400, detail="Invalid image path",)

    # Sécurité : s'assurer que le fichier est bien sous UPLOAD_ROOT
    try:
        target_path.relative_to(UPLOAD_ROOT)
    except ValueError:
        raise HTTPException(status_code=400,detail="Invalid image path")

    # 1) Supprimer le fichier (silencieusement s'il n'existe plus)
    try:
        target_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.exception("Failed to delete image %s: %s", target_path, exc)
        raise HTTPException(status_code=500, detail="Failed to delete image")

    # 2) Nettoyer les répertoires shardés vides, jusqu'à UPLOAD_ROOT
    for parent in target_path.parents:
        if parent == UPLOAD_ROOT:
            break
        try:
            parent.rmdir()  # succès seulement si le dossier est vide
        except OSError:
            # Dossier non vide ou autre problème "normal" -> on arrête silencieusement
            break
        except Exception as exc:
            logger.exception("Failed to cleanup directory %s: %s", parent, exc)
            break

