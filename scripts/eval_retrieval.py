"""Retrieval quality of a knowledge-base file, measured with embeddings only (no LLM, no Groq quota).

    python scripts/eval_retrieval.py [knowledge_base.json] [queries.json]

For every query in data/eval/retrieval_queries.json it embeds the query exactly as the diagnosis service does, asks
an in-memory Chroma collection built from the file for the top 3 records and reports:

* category hit@3  - a record of the expected equipment type is among the top 3
* strict hit@3    - the expected record id is among the top 3 (only queries that name one AND whose record is still in the file;
                    queries whose expected record was removed are counted separately, their labels are never edited)
* top-1 similarity (mean) and how many queries reach the 0.50 "close match" threshold on their top record
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db.seed import load_records, seed_knowledge_base  # noqa: E402
from app.db.vector_store import get_or_create_collection  # noqa: E402
from app.services.embedding_service import create_embedder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
kb_path = Path(args[0]) if args else ROOT / "data" / "knowledge_base.json"
queries = json.loads((Path(args[1]) if len(args) > 1 else ROOT / "data" / "eval" / "retrieval_queries.json").read_text(encoding="utf-8"))
settings = Settings()
threshold = settings.low_confidence_threshold

embedder = create_embedder(settings.embedding_backend, settings.embedding_model_name, settings.embedding_model_dir)
collection = get_or_create_collection(chromadb.EphemeralClient(), f"eval_{uuid.uuid4().hex}")
records = load_records(kb_path)
seed_knowledge_base(collection, embedder, records)

kb_ids = {r.id for r in records}
kb_categories = {r.equipment_type.lower() for r in records}
# a query whose category no longer exists in the knowledge base cannot be answered by it: leave it out of the measurement
dropped = [q for q in queries if q["category"].lower() not in kb_categories | {"none"}]
total_queries = len(queries)
queries = [q for q in queries if q not in dropped]

rows = []
for item in queries:
    raw = collection.query(query_embeddings=[embedder.embed([item["q"]])[0]], n_results=3, include=["metadatas", "distances"])
    hits = [(i, m["equipment_type"], round(1 - d, 4)) for i, m, d in zip(raw["ids"][0], raw["metadatas"][0], raw["distances"][0])]
    cat_hit = any(t.lower() == item["category"].lower() for _, t, _ in hits)
    named = "expected_id" in item and item["expected_id"] in kb_ids
    strict = any(i == item["expected_id"] for i, _, _ in hits) if named else None
    rows.append({**item, "top3": hits, "category_hit": cat_hit, "strict_hit": strict, "top1": hits[0][2]})

n = len(rows)
strict_rows = [r for r in rows if r["strict_hit"] is not None]
removed_expected = [q for q in queries if "expected_id" in q and q["expected_id"] not in kb_ids]
print(f"KB: {kb_path.name} | {len(records)} records | {len({r.equipment_type for r in records})} categories | {total_queries} queries, {len(dropped)} dropped (category not in KB), {n} measured")
print(f"queries naming an expected record that is no longer in the file: {len(removed_expected)}")
print(f"category hit@3      : {sum(r['category_hit'] for r in rows)}/{n} = {sum(r['category_hit'] for r in rows) / n:.0%}")
print(f"strict hit@3        : {sum(r['strict_hit'] for r in strict_rows)}/{len(strict_rows)} (queries whose expected record still exists)")
print(f"mean top-1 similarity: {sum(r['top1'] for r in rows) / n:.3f}")
print(f"top-1 >= {threshold}      : {sum(r['top1'] >= threshold for r in rows)}/{n}")
good = [r['top1'] for r in rows if r['category_hit'] and r['top3'][0][1].lower() == r['category'].lower()]
bad = [r['top1'] for r in rows if not (r['top3'][0][1].lower() == r['category'].lower())]
print(f"mean top-1 sim when top-1 is the right category: {sum(good) / max(1, len(good)):.3f} (n={len(good)}) | when it is not: {sum(bad) / max(1, len(bad)):.3f} (n={len(bad)})")
print(f"wrong top-1 that still clears {threshold}: {sum(1 for r in rows if r['top3'][0][1].lower() != r['category'].lower() and r['top1'] >= threshold)}")
if "--detail" in sys.argv:
    for r in rows:
        print(("OK  " if r["category_hit"] else "MISS"), f"{r['top1']:.2f}", r["category"], "|", r["q"][:60], "->", [(i, t, s) for i, t, s in r["top3"]])
if "--save" in sys.argv:  # raw per-query results, for comparing two runs; not written by default
    out = ROOT / "data" / "eval" / f"result_{kb_path.stem}.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
