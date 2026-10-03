"""Review workflow + knowledge-base growth, at the service level.

ChromaDB is mocked (``MagicMock``) wherever we only need to see *what would be written*; a real
in-memory Chroma is used where we need real counts / real deletions.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.exceptions import KnowledgeBaseUpdateError, ReviewConflictError, TicketNotFoundError
from app.db.seed import load_records, seed_knowledge_base
from app.db.session import add_missing_columns, init_db
from app.models.ticket import Ticket
from app.schemas.enums import ReviewPriority, ReviewStatus, Severity
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.review_service import ReviewService
from app.services.ticket_service import TicketService
from tests.conftest import KNOWLEDGE_BASE_PATH

REPORT = "laptop battery drains within an hour and the laptop shuts down at 30 percent"
AI_CAUSE = "The battery has lost capacity."
AI_FIX = "Replace the battery."


@pytest.fixture
def session(db_session_factory):
    s = db_session_factory()
    yield s
    s.close()


@pytest.fixture
def mock_collection():
    collection = MagicMock()
    # Behave like a healthy index: a similarity query finds the record that was just written.
    collection.query.side_effect = lambda **kwargs: {"ids": [[collection.upsert.call_args.kwargs["ids"][0]]]}
    return collection


@pytest.fixture
def kb(mock_collection, fake_embedder):
    return KnowledgeBaseService(mock_collection, fake_embedder)


@pytest.fixture
def review(session, kb):
    return ReviewService(session, kb)


def make_ticket(session, severity=Severity.MEDIUM, source="text", description=REPORT) -> Ticket:
    return TicketService(session).create_ticket(
        source=source,
        description=description,
        severity=severity,
        diagnosis=AI_CAUSE,
        recommended_action=AI_FIX,
        confidence_score=0.27,
    )


def written(mock_collection, call=-1) -> dict:
    """The metadata of the record written by the n-th ``upsert`` call."""
    return mock_collection.upsert.call_args_list[call].kwargs["metadatas"][0]


# --- new tickets: pending, with a priority --------------------------------------------------------
@pytest.mark.parametrize(
    "severity, priority",
    [(Severity.HIGH, ReviewPriority.HIGH), (Severity.MEDIUM, ReviewPriority.HIGH), (Severity.LOW, ReviewPriority.LOW)],
)
def test_new_tickets_are_pending_and_medium_or_high_severity_gets_high_review_priority(session, severity, priority):
    ticket = make_ticket(session, severity)

    assert ticket.review_status == ReviewStatus.PENDING
    assert ticket.review_priority == priority
    assert ticket.reviewed_at is None and ticket.kb_record_id is None
    assert ticket.corrected_root_cause is None and ticket.corrected_fix is None


# --- confirming ---------------------------------------------------------------------------------------
def test_confirming_marks_the_ticket_confirmed_and_adds_the_original_ai_diagnosis_to_the_kb(session, review, mock_collection):
    ticket = make_ticket(session)

    review.confirm(ticket.id)

    assert ticket.review_status == ReviewStatus.CONFIRMED and ticket.reviewed_at is not None
    assert ticket.corrected_root_cause is None and ticket.corrected_fix is None
    assert ticket.kb_record_id.startswith(f"VC-{ticket.id}-")

    mock_collection.upsert.assert_called_once()
    record = written(mock_collection)
    assert record["source"] == "verified" and record["review_status"] == "confirmed"
    assert record["issue_description"] == REPORT  # what a future query will be matched against
    assert (record["root_cause"], record["recommended_fix"]) == (AI_CAUSE, AI_FIX)  # the AI's own answer
    assert record["severity"] == "medium" and record["ticket_id"] == ticket.id
    assert mock_collection.upsert.call_args.kwargs["ids"] == [ticket.kb_record_id]


def test_the_report_text_is_what_gets_embedded_with_the_equipment_type_when_given(session, kb, mock_collection):
    review = ReviewService(session, kb)
    plain, typed = make_ticket(session), make_ticket(session)

    review.confirm(plain.id)
    review.confirm(typed.id, equipment_type="  laptop ")

    assert mock_collection.upsert.call_args_list[0].kwargs["documents"] == [REPORT]
    assert mock_collection.upsert.call_args_list[1].kwargs["documents"] == [f"laptop: {REPORT}"]
    assert written(mock_collection, 1)["equipment_type"] == "laptop"
    assert written(mock_collection, 0)["equipment_type"] == "unspecified"


def test_the_stored_vector_is_the_embedding_of_the_report(session, kb, mock_collection, fake_embedder):
    ticket = make_ticket(session)

    ReviewService(session, kb).confirm(ticket.id)

    assert mock_collection.upsert.call_args.kwargs["embeddings"] == [fake_embedder.embed([REPORT])[0]]


# --- correcting ------------------------------------------------------------------------------------------
def test_correcting_stores_the_technicians_version_beside_the_ai_original_and_adds_the_corrected_case(session, review, mock_collection):
    ticket = make_ticket(session)

    review.correct(ticket.id, "  Faulty battery controller board  ", "Replace the controller board.")

    assert ticket.review_status == ReviewStatus.CORRECTED
    assert (ticket.corrected_root_cause, ticket.corrected_fix) == ("Faulty battery controller board", "Replace the controller board.")
    assert (ticket.diagnosis, ticket.recommended_action) == (AI_CAUSE, AI_FIX)  # original kept for comparison
    record = written(mock_collection)
    assert record["review_status"] == "corrected"
    assert (record["root_cause"], record["recommended_fix"]) == ("Faulty battery controller board", "Replace the controller board.")


def test_a_photo_ticket_is_matched_by_the_ais_visual_findings_not_its_file_name(session, review, mock_collection):
    ticket = make_ticket(session, source="image", description="[image upload] pipes.jpg")

    review.confirm(ticket.id)

    assert written(mock_collection)["issue_description"] == AI_CAUSE  # the model's visual description
    assert "[image upload]" not in mock_collection.upsert.call_args.kwargs["documents"][0]


# --- status transitions --------------------------------------------------------------------------------------
def test_confirming_twice_is_harmless_and_does_not_add_a_second_record(session, review, mock_collection):
    ticket = make_ticket(session)
    review.confirm(ticket.id)
    first_id = ticket.kb_record_id

    review.confirm(ticket.id)

    assert ticket.review_status == ReviewStatus.CONFIRMED and ticket.kb_record_id == first_id
    mock_collection.upsert.assert_called_once()


def test_a_confirmed_ticket_can_still_be_corrected_and_updates_the_same_record(session, review, mock_collection):
    ticket = make_ticket(session)
    review.confirm(ticket.id)
    record_id = ticket.kb_record_id

    review.correct(ticket.id, "Actually a swollen cell.", "Replace the pack.")

    assert ticket.review_status == ReviewStatus.CORRECTED and ticket.kb_record_id == record_id
    assert mock_collection.upsert.call_count == 2
    assert [c.kwargs["ids"] for c in mock_collection.upsert.call_args_list] == [[record_id], [record_id]]
    assert written(mock_collection)["root_cause"] == "Actually a swollen cell."  # updated in place, not duplicated


def test_a_correction_can_be_edited_again(session, review, mock_collection):
    ticket = make_ticket(session)
    review.correct(ticket.id, "First attempt cause.", "First attempt fix.")
    review.correct(ticket.id, "Better cause found.", "Better fix found.")

    assert ticket.corrected_root_cause == "Better cause found."
    assert written(mock_collection)["root_cause"] == "Better cause found."
    assert len({c.kwargs["ids"][0] for c in mock_collection.upsert.call_args_list}) == 1  # one record


def test_a_corrected_ticket_cannot_be_confirmed_and_nothing_changes(session, review, mock_collection):
    ticket = make_ticket(session)
    review.correct(ticket.id, "Real cause here.", "Real fix here.")
    mock_collection.upsert.reset_mock()

    with pytest.raises(ReviewConflictError):
        review.confirm(ticket.id)

    assert ticket.review_status == ReviewStatus.CORRECTED
    assert ticket.corrected_root_cause == "Real cause here."
    mock_collection.upsert.assert_not_called()


def test_reviewing_an_unknown_ticket_is_a_not_found_error(review):
    with pytest.raises(TicketNotFoundError):
        review.confirm(9999)
    with pytest.raises(TicketNotFoundError):
        review.correct(9999, "cause cause", "fix fix fix")


# --- unreviewed tickets never reach the knowledge base ---------------------------------------------------------------
def test_pending_tickets_are_never_added_to_the_knowledge_base(session, review, mock_collection):
    pending_a, pending_b = make_ticket(session), make_ticket(session, Severity.HIGH)
    reviewed = make_ticket(session)

    review.confirm(reviewed.id)
    # other things that happen to pending tickets must not add them either
    TicketService(session).save_feedback(pending_a.id, True)  # a quick thumbs-up is not a review
    TicketService(session).list_tickets(1, 20)

    assert [c.kwargs["ids"] for c in mock_collection.upsert.call_args_list] == [[reviewed.kb_record_id]]
    for pending in (pending_a, pending_b):
        assert pending.review_status == ReviewStatus.PENDING and pending.kb_record_id is None


def test_creating_diagnoses_never_writes_to_the_knowledge_base(session, mock_collection):
    for severity in (Severity.LOW, Severity.MEDIUM, Severity.HIGH):
        make_ticket(session, severity)

    mock_collection.upsert.assert_not_called()


def test_the_service_refuses_to_add_a_pending_ticket_even_if_called_directly(session, kb):
    ticket = make_ticket(session)
    ticket.kb_record_id = "VC-x"  # even with an id, pending must not be written

    with pytest.raises(ValueError):
        kb.upsert_ticket_case(ticket)


# --- failures leave things consistent -----------------------------------------------------------------------------------
def test_if_the_vector_store_fails_the_ticket_stays_pending(session, review, mock_collection):
    mock_collection.upsert.side_effect = RuntimeError("chroma is down")
    ticket = make_ticket(session)

    with pytest.raises(KnowledgeBaseUpdateError):
        review.confirm(ticket.id)

    session.expire_all()
    fresh = session.get(Ticket, ticket.id)
    assert fresh.review_status == ReviewStatus.PENDING
    assert fresh.kb_record_id is None and fresh.reviewed_at is None


def test_if_the_database_commit_fails_the_new_knowledge_base_record_is_removed_again(session, review, mock_collection, monkeypatch):
    ticket = make_ticket(session)
    monkeypatch.setattr(session, "commit", MagicMock(side_effect=RuntimeError("disk full")))

    with pytest.raises(RuntimeError):
        review.confirm(ticket.id)

    mock_collection.delete.assert_called_once()  # no orphan record pointing at nothing


# --- seed vs verified statistics (real in-memory Chroma) ----------------------------------------------------------------------
def test_stats_split_the_knowledge_base_into_seed_and_verified_records(session, knowledge_base):
    seed_count = knowledge_base.stats().total
    review = ReviewService(session, knowledge_base)
    confirmed, corrected, pending = make_ticket(session), make_ticket(session), make_ticket(session)

    review.confirm(confirmed.id)
    review.correct(corrected.id, "A real cause.", "A real fix.")

    stats = knowledge_base.stats()
    assert stats.total == seed_count + 2
    assert (stats.seed, stats.verified) == (seed_count, 2)
    assert (stats.verified_confirmed, stats.verified_corrected) == (1, 1)
    assert pending.kb_record_id is None  # still not in the store


def test_records_stored_before_the_source_field_existed_count_as_seed(seeded_collection, fake_embedder):
    old = seeded_collection.get(ids=["KB-001"], include=["metadatas"])["metadatas"][0]
    old.pop("source", None)
    seeded_collection.update(ids=["KB-001"], metadatas=[old])  # now has no 'source' at all

    stats = KnowledgeBaseService(seeded_collection, fake_embedder).stats()

    assert stats.verified == 0 and stats.seed == stats.total


# --- re-seeding must never destroy verified knowledge ------------------------------------------------------------------------------
def test_reseeding_keeps_verified_cases_even_when_seed_records_are_removed(session, knowledge_base, seeded_collection, fake_embedder):
    ticket = make_ticket(session)
    ReviewService(session, knowledge_base).confirm(ticket.id)
    seed_records = load_records(KNOWLEDGE_BASE_PATH)

    report = seed_knowledge_base(seeded_collection, fake_embedder, seed_records[:-3])  # 3 seed records removed from the file

    assert report.deleted == 3  # only seed records are deleted...
    assert seeded_collection.get(ids=[ticket.kb_record_id])["ids"] == [ticket.kb_record_id]  # ...the verified one survives
    assert knowledge_base.stats().verified == 1


def test_seeding_twice_does_not_change_the_verified_count(session, knowledge_base, seeded_collection, fake_embedder):
    ReviewService(session, knowledge_base).confirm(make_ticket(session).id)

    seed_knowledge_base(seeded_collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH))
    seed_knowledge_base(seeded_collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH))

    assert knowledge_base.stats().verified == 1


# --- restoring verified cases after the vector store was wiped -----------------------------------------------------------------------
def test_verified_cases_are_restored_from_the_database_if_the_vector_store_lost_them(session, knowledge_base, seeded_collection):
    review = ReviewService(session, knowledge_base)
    kept, lost, pending = make_ticket(session), make_ticket(session), make_ticket(session)
    review.confirm(kept.id)
    review.correct(lost.id, "Cause that must survive.", "Fix that must survive.")
    seeded_collection.delete(ids=[lost.kb_record_id])  # the vector store loses one record

    restored = knowledge_base.restore_missing(session.query(Ticket).all())

    assert restored == 1  # only the missing one; 'kept' was present and 'pending' is not eligible
    back = seeded_collection.get(ids=[lost.kb_record_id], include=["metadatas"])["metadatas"][0]
    assert back["root_cause"] == "Cause that must survive." and back["source"] == "verified"


# --- the startup migration for databases created before these columns existed ---------------------------------------------------------------
def test_an_old_database_without_the_review_columns_is_upgraded_in_place():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:  # the schema as it was BEFORE the review feature, with a row in it
        conn.execute(text(
            "CREATE TABLE tickets (id INTEGER PRIMARY KEY, source VARCHAR(16), description TEXT, severity VARCHAR(16), "
            "diagnosis TEXT, recommended_action TEXT, confidence_score FLOAT, similar_cases JSON, created_at DATETIME)"
        ))
        conn.execute(text(
            "INSERT INTO tickets VALUES (1, 'text', 'old report', 'HIGH', 'old diagnosis', 'old action', 0.5, '[]', '2026-01-01 00:00:00')"
        ))

    added = add_missing_columns(engine)

    assert {a.split(".")[1] for a in added} == {
        "review_status", "review_priority", "corrected_root_cause", "corrected_fix", "reviewed_at",
        "kb_record_id", "review_equipment_type",
        "diagnosis_basis", "llm_confidence",  # added for /stats
        "failed_kb_record_id",  # added for thumbs-down "failed_fix" records
    }
    assert add_missing_columns(engine) == []  # idempotent
    from sqlalchemy.orm import sessionmaker

    old = sessionmaker(bind=engine)().get(Ticket, 1)
    assert old.review_status == ReviewStatus.PENDING and old.review_priority == ReviewPriority.LOW  # defaults applied
    assert old.diagnosis == "old diagnosis"  # nothing else touched


def test_init_db_on_a_fresh_database_adds_nothing_extra():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    init_db(engine)
    assert add_missing_columns(engine) == []


# --- ChromaDB index misses: verify after every write, repair if needed -------------------------------------------------------
class UnindexedWrites:
    """A real collection that behaves like the Chroma index bug seen in the wild: written records are stored
    (``get`` finds them) but missing from similarity results until they are written AGAIN."""

    def __init__(self, real, writes_needed: int):
        self._real, self._writes_needed, self.upserts = real, writes_needed, 0

    def upsert(self, **kwargs):
        self.upserts += 1
        return self._real.upsert(**kwargs)

    def query(self, **kwargs):
        result = self._real.query(**kwargs)
        if self.upserts < self._writes_needed:  # not indexed yet: verified cases are invisible
            result["ids"] = [[i for i in result["ids"][0] if not i.startswith("VC-")]]
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_a_record_missing_from_the_search_index_is_detected_and_re_written(session, seeded_collection, fake_embedder, caplog):
    flaky = UnindexedWrites(seeded_collection, writes_needed=2)  # the first write is not searchable
    ticket = make_ticket(session)

    with caplog.at_level("WARNING", logger="app.services.knowledge_base_service"):
        ReviewService(session, KnowledgeBaseService(flaky, fake_embedder)).confirm(ticket.id)

    assert flaky.upserts == 2  # the original write + one repair
    hit = seeded_collection.query(query_embeddings=[fake_embedder.embed([REPORT])[0]], n_results=1)["ids"][0][0]
    assert hit == ticket.kb_record_id  # genuinely findable now
    assert any(r.getMessage() == "knowledge_base_index_repaired" for r in caplog.records)


def test_a_healthy_index_needs_no_repair_write(session, review, mock_collection):
    review.confirm(make_ticket(session).id)

    mock_collection.upsert.assert_called_once()  # verified with a query, never re-written
    mock_collection.query.assert_called_once()


def test_if_the_repair_never_works_the_review_is_still_saved_and_the_problem_is_logged(session, seeded_collection, fake_embedder, caplog):
    flaky = UnindexedWrites(seeded_collection, writes_needed=999)  # permanently unsearchable
    ticket = make_ticket(session)

    with caplog.at_level("ERROR", logger="app.services.knowledge_base_service"):
        ReviewService(session, KnowledgeBaseService(flaky, fake_embedder)).confirm(ticket.id)

    assert ticket.review_status == ReviewStatus.CONFIRMED  # the technician's work is not thrown away...
    assert flaky.upserts == 3  # ...after a bounded number of attempts (1 write + 2 repairs)...
    assert any(r.getMessage() == "knowledge_base_index_miss" for r in caplog.records)  # ...and it is logged loudly


def test_every_confirmed_case_is_searchable_across_many_fresh_real_collections(session, fake_embedder):
    """Regression guard against REAL ChromaDB: before the repair step roughly 1 in 8 of these failed,
    so 40 rounds would have exposed it about 99.6% of the time."""
    import uuid

    import chromadb

    from app.db.vector_store import get_or_create_collection

    client = chromadb.EphemeralClient()
    query_vector = fake_embedder.embed([REPORT])[0]
    for _ in range(40):
        collection = get_or_create_collection(client, f"guard_{uuid.uuid4().hex}")
        seed_knowledge_base(collection, fake_embedder, load_records(KNOWLEDGE_BASE_PATH))
        ticket = make_ticket(session)
        ReviewService(session, KnowledgeBaseService(collection, fake_embedder)).confirm(ticket.id)

        assert collection.query(query_embeddings=[query_vector], n_results=3)["ids"][0][0] == ticket.kb_record_id
        client.delete_collection(collection.name)
