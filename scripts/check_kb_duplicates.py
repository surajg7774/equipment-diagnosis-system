"""Find near-duplicate records in the seed file with the REAL embedder (the text the system actually embeds).

    python scripts/check_kb_duplicates.py [knowledge_base.json] [threshold]

Prints every pair at or above the threshold (default 0.90) and the closest pairs below it. Exit code 1 if any pair
reaches the threshold, so it can gate a change. Needs the embedding model (downloaded on first use); no LLM.
"""
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings  # noqa: E402
from app.db.seed import load_records, record_to_embedding_text  # noqa: E402
from app.services.diagnosis_service import cosine_similarity  # noqa: E402
from app.services.embedding_service import create_embedder  # noqa: E402

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "knowledge_base.json"
threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.90
settings = Settings()
records = load_records(path)
embedder = create_embedder(settings.embedding_backend, settings.embedding_model_name, settings.embedding_model_dir)
vectors = embedder.embed([record_to_embedding_text(r) for r in records])

pairs = sorted(((cosine_similarity(vectors[i], vectors[j]), records[i], records[j]) for i, j in combinations(range(len(records)), 2)), key=lambda p: -p[0])
dupes = [p for p in pairs if p[0] >= threshold]
print(f"{len(records)} records, {len(pairs)} pairs checked, threshold {threshold}: {len(dupes)} pair(s) at or above it")
for sim, a, b in pairs[: max(len(dupes), 12)]:
    flag = "DUPLICATE" if sim >= threshold else "close    "
    print(f"{flag} {sim:.3f}  {a.id} [{a.equipment_type}] {a.issue_description[:58]!r}  <->  {b.id} [{b.equipment_type}] {b.issue_description[:58]!r}")
sys.exit(1 if dupes else 0)
