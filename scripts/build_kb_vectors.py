"""Compute the document vectors for the seed file ahead of time, so a cold start does not have to.

    python scripts/build_kb_vectors.py            # (re)write data/knowledge_base_vectors.json
    python scripts/build_kb_vectors.py --check    # exit 1 if the stored vectors are missing or out of date; writes nothing

Why: on Render's free instance (about 0.1 CPU) embedding the seed records at every cold start took minutes. The vectors
only depend on the text we embed for each record ("<equipment type>: <issue description>"), so they are computed once
here, with the real model, and committed. Seeding uses a stored vector when the SHA-256 of the record's current text
matches, and embeds only the records without one. Run this script after editing data/knowledge_base.json (a test fails
until you do).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings  # noqa: E402
from app.db.seed import VECTORS_MODEL, load_records, record_to_embedding_text, text_fingerprint  # noqa: E402
from app.services.embedding_service import create_embedder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KB_PATH = ROOT / "data" / "knowledge_base.json"
OUT_PATH = ROOT / "data" / "knowledge_base_vectors.json"
DECIMALS = 6  # float32 precision is about 7 digits; rounding to 6 changes cosine similarity by less than 1e-6


def stale_ids(records, stored: dict) -> list[str]:
    """Record ids whose stored vector is missing or was made from different text, plus ids stored for deleted records."""
    bad = [r.id for r in records if stored.get(r.id, {}).get("text_sha256") != text_fingerprint(record_to_embedding_text(r))]
    return bad + sorted(set(stored) - {r.id for r in records})


def main() -> int:
    records = load_records(KB_PATH)
    stored = {}
    if OUT_PATH.is_file():
        stored = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("vectors", {})

    if "--check" in sys.argv:
        bad = stale_ids(records, stored)
        print(f"{len(records)} records, {len(bad)} with a missing or out-of-date stored vector" + (f": {bad[:10]}" if bad else ""))
        return 1 if bad else 0

    settings = Settings()
    embedder = create_embedder(settings.embedding_backend, settings.embedding_model_name, settings.embedding_model_dir)
    texts = [record_to_embedding_text(r) for r in records]
    vectors = embedder.embed(texts)
    lines = []
    for record, text, vector in zip(records, texts, vectors):
        entry = {"text_sha256": text_fingerprint(text), "vector": [round(float(x), DECIMALS) for x in vector]}
        lines.append(f"  {json.dumps(record.id)}: {json.dumps(entry, separators=(',', ':'))}")
    header = {"model": VECTORS_MODEL, "dimension": len(vectors[0]), "decimals": DECIMALS}
    body = "{\n" + ",\n".join(f"{json.dumps(k)}: {json.dumps(v)}" for k, v in header.items()) + ',\n"vectors": {\n' + ",\n".join(lines) + "\n}\n}\n"
    json.loads(body)  # must be valid JSON
    OUT_PATH.write_text(body, encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}: {len(records)} vectors of {len(vectors[0])} numbers, {OUT_PATH.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
