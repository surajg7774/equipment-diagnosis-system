"""Download the ONNX embedding model (~80 MB) into EMBEDDING_MODEL_DIR. Meant for the BUILD step on Render.

    python scripts/download_embedding_model.py            # a failed download only prints a warning (the app downloads at start-up as before)
    python scripts/download_embedding_model.py --strict   # a failed download fails the build

Why: without this the model is downloaded from Chroma's CDN the first time the app embeds anything, which on a host whose
disk is wiped when it sleeps means on EVERY cold start. The build step runs once per deploy, and the folder it fills
(EMBEDDING_MODEL_DIR, inside the project) is part of what gets deployed.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings  # noqa: E402
from app.services.embedding_service import create_embedder  # noqa: E402


def main() -> int:
    settings = Settings()
    if settings.embedding_backend != "onnx":
        print("EMBEDDING_BACKEND is not onnx: nothing to download here.")
        return 0
    where = settings.embedding_model_dir or "Chroma's default cache (set EMBEDDING_MODEL_DIR to keep it in the project)"
    started = time.perf_counter()
    try:
        create_embedder(settings.embedding_backend, settings.embedding_model_name, settings.embedding_model_dir).load()
    except Exception as exc:  # network or CDN problem
        print(f"WARNING: could not download the embedding model into {where}: {type(exc).__name__}: {exc}")
        return 1 if "--strict" in sys.argv else 0
    print(f"embedding model ready in {where} ({time.perf_counter() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
