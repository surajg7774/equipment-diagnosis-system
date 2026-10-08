"""The seed file itself: every record is complete, documented, and not a duplicate.

The knowledge base holds only records that a public page backs: the cited page states the problem, its cause and a
remedy, and the record paraphrases it. There are no unverified "general knowledge" records. These tests keep it that
way when someone adds more: required fields, `source_type` always "documented", a public URL on every record, vendor
blogs labelled as such, an audit entry for every record, and no duplicate or near-duplicate text. (The near-duplicate
check with the REAL embedder is in test_integration_seed_quality.py.)
"""

import json
import re
from collections import Counter
from itertools import combinations
from urllib.parse import urlparse

import pytest

from app.db.seed import load_records, seed_if_empty, seed_knowledge_base
from app.schemas.knowledge_base import KnowledgeBaseRecord
from tests.conftest import KNOWLEDGE_BASE_PATH

RAW = json.loads(KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8"))
RECORDS = load_records(KNOWLEDGE_BASE_PATH)
AUDIT_PATH = KNOWLEDGE_BASE_PATH.parent.parent / "docs" / "kb_source_review.md"
ALLOWED_SOURCE_TYPES = {"documented"}
CATEGORIES = {
    "pump", "motor", "printer", "HVAC", "conveyor belt", "generator", "air compressor", "boiler", "refrigerator/chiller",
    "CNC machine", "forklift", "UPS", "laptop/desktop", "router/network switch", "CCTV", "water purifier",
    "washing machine", "elevator", "solar inverter",
}
# Pages from vendors, retailers, maintenance-software firms and other third parties (no primary source was found for
# these topics). Their source_name must say so, so a reader is never led to think they are manufacturer documentation.
VENDOR_HOSTS = {
    "coleindust.com", "fabrico.io", "racklify.com", "espwaterproducts.com", "asurion.com", "infraspeak.com",
    "electricalacademia.com",
}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


# --- shape ---------------------------------------------------------------------------------------------------------------
def test_the_file_is_not_truncated_and_every_category_is_present():
    categories = Counter(r.equipment_type for r in RECORDS)
    assert len(RECORDS) >= 100
    assert set(categories) == CATEGORIES


def test_no_category_is_padded_or_empty():
    """A category may be small (a record exists only where a source does) but never empty or bloated."""
    for category, count in Counter(r.equipment_type for r in RECORDS).items():
        assert 5 <= count <= 15, f"{category}: {count} records"


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


def test_every_fix_is_given_step_by_step():
    for r in RECORDS:
        assert re.search(r"\b1\) ", r.recommended_fix), f"{r.id}: fix is not step-wise"


def test_all_three_severity_levels_are_used():
    assert {r.severity.value for r in RECORDS} == {"low", "medium", "high"}


def test_dangerous_equipment_carries_the_safety_notes_its_sources_give():
    """A safety note is written only where the cited page says it, so not every record has one; these have some."""
    for category in ("boiler", "air compressor", "solar inverter", "elevator", "forklift", "CNC machine"):
        assert any(r.safety_note for r in RECORDS if r.equipment_type == category), category


def test_no_record_tells_the_reader_to_bypass_a_safety_device():
    """Where a bypass is mentioned at all it is a warning not to do it (the sources say so)."""
    defeat = re.compile(r"(bypass|jumper out|defeat|disable)[^.]{0,30}(safety|interlock|cutout|cutoff|relay|breaker|protection|guard)")
    warning = re.compile(r"(do not|never|don't)[^.]{0,40}(bypass|jumper|disable|defeat)")
    for r in RECORDS:
        text = f"{r.recommended_fix} {r.safety_note or ''}".lower()
        assert not defeat.search(text) or warning.search(text), r.id


# --- sources: every record is documented ---------------------------------------------------------------------------------
def test_every_record_states_its_source_type_and_only_allowed_values_are_used():
    assert [item.get("source_type") for item in RAW if item.get("source_type") not in ALLOWED_SOURCE_TYPES] == []


def test_every_record_cites_a_public_page():
    for r in RECORDS:
        assert r.source_type == "documented", r.id
        assert r.source_name and len(r.source_name) >= 10, r.id
        assert r.source_url and re.fullmatch(r"https://[\w.-]+\.[a-z]{2,}/\S*", r.source_url), r.id


def test_vendor_and_third_party_sources_say_so_in_their_name():
    vendor_records = [r for r in RECORDS if _host(r.source_url) in VENDOR_HOSTS]
    assert vendor_records, "the vendor list no longer matches the file"
    for r in vendor_records:
        assert re.search(r"blog|third-party|vendor", r.source_name, re.IGNORECASE), f"{r.id}: {r.source_name}"


def test_a_source_page_is_never_attached_to_a_record_from_a_different_field():
    """Cheap guard against copy-paste slips: a cited page is only reused within sensible groups of records."""
    per_url = Counter(r.source_url for r in RECORDS)
    assert max(per_url.values()) <= 14  # one page covers at most a dozen or so problems
    for url in per_url:
        categories = {r.equipment_type for r in RECORDS if r.source_url == url}
        assert len(categories) <= 2, f"{url} is cited for {sorted(categories)}"


# --- the audit file (docs/kb_source_review.md, not shipped in the app) ---------------------------------------------------
def _audit_rows():
    rows = {}
    for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if len(cells) == 5 and re.fullmatch(r"KB-\d{3}", cells[0]):
            rows[cells[0]] = {"category": cells[1], "kind": cells[2], "url": cells[3], "quote": cells[4].strip('"')}
    return rows


def test_every_record_has_an_audit_entry_with_the_same_link_and_a_short_supporting_line():
    audit = _audit_rows()
    assert set(audit) == {r.id for r in RECORDS}
    for r in RECORDS:
        row = audit[r.id]
        assert row["url"] == r.source_url and row["category"] == r.equipment_type, r.id
        assert 2 <= len(row["quote"].split()) < 15, f"{r.id}: supporting line must be under 15 words"


def test_the_audit_file_marks_vendor_sources_as_vendor_sources():
    audit = _audit_rows()
    for r in RECORDS:
        if _host(r.source_url) in VENDOR_HOSTS:
            assert "vendor" in audit[r.id]["kind"].lower(), r.id


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
    documented = next(r for r in RECORDS if r.equipment_type == "air compressor")
    metadata = seeded_collection.get(ids=[documented.id], include=["metadatas"])["metadatas"][0]
    assert metadata["source_url"] == documented.source_url and metadata["source_type"] == "documented"

    body = client.post("/api/v1/diagnose", json={"description": documented.issue_description}).json()
    case = next(c for c in body["similar_cases"] if c["id"] == documented.id)
    assert (case["source_type"], case["source_name"], case["source_url"]) == ("documented", documented.source_name, documented.source_url)
    assert case["source"] == "seed"  # the existing field is untouched: how the record entered the knowledge base


def test_seeding_the_file_twice_or_at_startup_never_duplicates(seeded_collection, fake_embedder):
    before = seeded_collection.count()

    again = seed_knowledge_base(seeded_collection, fake_embedder, RECORDS)
    skipped = seed_if_empty(seeded_collection, fake_embedder, KNOWLEDGE_BASE_PATH)

    assert before == seeded_collection.count() == len(RECORDS) == again.total_in_store
    assert skipped is None  # a non-empty store is not re-seeded at startup
