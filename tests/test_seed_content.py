"""The seed file itself: every record is complete, sourced honestly, and not a duplicate.

The knowledge base was expanded from 28 to ~200 researched records. These tests keep it that way when someone adds more:
required fields, allowed source types, a URL on every "documented" record and none on the others, no duplicate or
near-duplicate text. (The near-duplicate check with the REAL embedder is in test_integration_seed_quality.py.)
"""

import json
import re
from collections import Counter
from itertools import combinations

import pytest

from app.db.seed import load_records, seed_if_empty, seed_knowledge_base
from app.schemas.knowledge_base import KnowledgeBaseRecord
from tests.conftest import KNOWLEDGE_BASE_PATH

RAW = json.loads(KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8"))
RECORDS = load_records(KNOWLEDGE_BASE_PATH)
ALLOWED_SOURCE_TYPES = {"documented", "general_knowledge"}
ORIGINAL_CATEGORIES = {"pump", "motor", "printer", "HVAC", "conveyor belt", "generator"}
NEW_CATEGORIES = {
    "air compressor", "boiler", "refrigerator/chiller", "CNC machine", "forklift", "UPS", "laptop/desktop",
    "router/network switch", "CCTV", "water purifier", "washing machine", "elevator", "solar inverter",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


# --- shape ---------------------------------------------------------------------------------------------------------------
def test_there_are_150_to_200_records_in_about_twenty_categories():
    categories = Counter(r.equipment_type for r in RECORDS)
    assert 150 <= len(RECORDS) <= 200
    assert set(categories) >= ORIGINAL_CATEGORIES | NEW_CATEGORIES and len(categories) >= 15


def test_every_category_has_between_8_and_12_problems():
    for category, count in Counter(r.equipment_type for r in RECORDS).items():
        assert 8 <= count <= 12, f"{category}: {count} records"


def test_ids_are_unique_and_follow_the_kb_number_pattern():
    ids = [r.id for r in RECORDS]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"KB-\d{3}", i) for i in ids)


@pytest.mark.parametrize("record", RECORDS, ids=[r.id for r in RECORDS])
def test_every_record_has_all_required_fields_filled_in(record):
    assert record.equipment_type.strip()
    assert len(record.issue_description.strip()) >= 20 and record.issue_description.rstrip().endswith((".", "?"))
    assert len(record.root_cause.strip()) >= 20
    assert len(record.recommended_fix.strip()) >= 20
    assert record.severity.value in {"low", "medium", "high"}
    assert record.source == "seed" and record.outcome is None  # seed records carry no learned-outcome fields
    if record.safety_note is not None:
        assert len(record.safety_note.strip()) >= 10


def test_new_records_give_step_by_step_fixes():
    for r in RECORDS:
        if int(r.id[3:]) > 28:  # the original 28 keep their original prose
            assert re.search(r"\b1\) ", r.recommended_fix), f"{r.id}: fix is not step-wise"


def test_all_three_severity_levels_are_used():
    assert {r.severity.value for r in RECORDS} == {"low", "medium", "high"}


def test_electrical_gas_pressure_and_rotating_equipment_carries_safety_notes():
    """Not every record needs one, but the dangerous categories must have a good share of them."""
    for category in ("boiler", "air compressor", "solar inverter", "elevator", "forklift", "UPS", "CNC machine"):
        rows = [r for r in RECORDS if r.equipment_type == category]
        assert sum(1 for r in rows if r.safety_note) >= max(2, len(rows) // 4), category


# --- sources: honest labels ----------------------------------------------------------------------------------------------
def test_every_record_states_its_source_type_and_only_allowed_values_are_used():
    assert [item.get("source_type") for item in RAW if item.get("source_type") not in ALLOWED_SOURCE_TYPES] == []


def test_documented_records_cite_a_public_page_and_the_others_cite_nothing():
    for r in RECORDS:
        if r.source_type == "documented":
            assert r.source_name and len(r.source_name) >= 10, r.id
            assert r.source_url and re.fullmatch(r"https://[\w.-]+\.[a-z]{2,}/\S*", r.source_url), r.id
        else:
            assert r.source_type == "general_knowledge" and r.source_url is None and r.source_name is None, r.id


def test_a_source_page_is_never_attached_to_a_record_from_a_different_field():
    """Cheap guard against copy-paste slips: a cited page is only reused within sensible groups of records."""
    per_url = Counter(r.source_url for r in RECORDS if r.source_url)
    assert max(per_url.values()) <= 12  # one page covers at most a dozen problems
    for url in per_url:
        categories = {r.equipment_type for r in RECORDS if r.source_url == url}
        assert len(categories) <= 2, f"{url} is cited for {sorted(categories)}"


def test_both_kinds_exist_and_documented_is_the_majority():
    kinds = Counter(r.source_type for r in RECORDS)
    assert kinds["documented"] > kinds["general_knowledge"] > 0


# --- duplicates ----------------------------------------------------------------------------------------------------------
def test_no_two_records_describe_the_same_problem_in_the_same_words():
    for a, b in combinations(RECORDS, 2):
        if a.equipment_type != b.equipment_type:
            continue
        wa, wb = _words(a.issue_description), _words(b.issue_description)
        assert len(wa & wb) / len(wa | wb) < 0.8, f"{a.id} and {b.id} look like duplicates"
        assert a.recommended_fix != b.recommended_fix, f"{a.id} and {b.id} have the same fix"


# --- backwards compatibility and flow-through ----------------------------------------------------------------------------
def test_a_record_without_the_new_fields_is_still_valid():
    old = KnowledgeBaseRecord.model_validate(
        {"id": "KB-900", "equipment_type": "pump", "issue_description": "x", "root_cause": "y", "recommended_fix": "z", "severity": "low"}
    )
    assert (old.source_type, old.source_name, old.source_url, old.safety_note) == (None, None, None, None)


def test_the_source_fields_survive_seeding_and_come_back_with_a_similar_case(client, seeded_collection):
    documented = next(r for r in RECORDS if r.source_type == "documented" and r.equipment_type == "air compressor")
    metadata = seeded_collection.get(ids=[documented.id], include=["metadatas"])["metadatas"][0]
    assert metadata["source_url"] == documented.source_url and metadata["source_type"] == "documented"

    body = client.post("/api/v1/diagnose", json={"description": documented.issue_description}).json()
    case = next(c for c in body["similar_cases"] if c["id"] == documented.id)
    assert (case["source_type"], case["source_name"], case["source_url"]) == ("documented", documented.source_name, documented.source_url)
    assert case["source"] == "seed"  # the existing field is untouched: how the record entered the knowledge base


def test_a_general_knowledge_record_comes_back_without_a_link(client):
    general = next(r for r in RECORDS if r.source_type == "general_knowledge")
    body = client.post("/api/v1/diagnose", json={"description": general.issue_description}).json()
    case = next(c for c in body["similar_cases"] if c["id"] == general.id)
    assert case["source_type"] == "general_knowledge" and case["source_url"] is None


def test_seeding_the_expanded_file_twice_or_at_startup_never_duplicates(seeded_collection, fake_embedder):
    before = seeded_collection.count()

    again = seed_knowledge_base(seeded_collection, fake_embedder, RECORDS)
    skipped = seed_if_empty(seeded_collection, fake_embedder, KNOWLEDGE_BASE_PATH)

    assert before == seeded_collection.count() == len(RECORDS) == again.total_in_store
    assert skipped is None  # a non-empty store is not re-seeded at startup
