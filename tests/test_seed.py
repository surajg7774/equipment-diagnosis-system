"""Seed script tests: idempotency and data validation, against an in-memory Chroma."""

import json

import pytest

from app.db.seed import load_records, seed_knowledge_base
from tests.conftest import KNOWLEDGE_BASE_PATH


def test_knowledge_base_file_is_valid_and_sized_as_specified():
    records = load_records(KNOWLEDGE_BASE_PATH)
    assert 100 <= len(records) <= 300  # only documented records: the count follows the sources, not a target
    # Every severity level and every required equipment family is represented.
    assert {r.severity.value for r in records} == {"low", "medium", "high"}
    assert {r.equipment_type for r in records} >= {
        "pump", "motor", "printer", "HVAC", "conveyor belt", "generator"
    }


def test_seeding_twice_gives_same_result(seeded_collection, fake_embedder):
    records = load_records(KNOWLEDGE_BASE_PATH)
    assert seeded_collection.count() == len(records)

    report = seed_knowledge_base(seeded_collection, fake_embedder, records)  # second run

    assert seeded_collection.count() == len(records)  # no duplicates
    assert report.upserted == len(records) and report.deleted == 0


def test_seeding_removes_records_deleted_from_the_file(seeded_collection, fake_embedder):
    records = load_records(KNOWLEDGE_BASE_PATH)

    report = seed_knowledge_base(seeded_collection, fake_embedder, records[:-2])

    assert report.deleted == 2
    assert seeded_collection.count() == len(records) - 2


def test_duplicate_ids_are_rejected(tmp_path):
    record = json.loads(KNOWLEDGE_BASE_PATH.read_text())[0]
    bad_file = tmp_path / "kb.json"
    bad_file.write_text(json.dumps([record, record]))

    with pytest.raises(ValueError, match="Duplicate"):
        load_records(bad_file)
