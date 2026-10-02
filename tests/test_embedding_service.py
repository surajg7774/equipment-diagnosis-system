"""ONNX embedder: texts must be embedded in small batches (memory), without changing results."""

from app.services.embedding_service import OnnxEmbeddingService


class _RecordingFn:
    """Stands in for chroma's ONNX function: returns a distinctive vector per text."""

    def __init__(self):
        self.batch_sizes: list[int] = []

    def __call__(self, texts):
        self.batch_sizes.append(len(texts))
        return [[float(len(t)), 0.5] for t in texts]


def _service(fn) -> OnnxEmbeddingService:
    service = OnnxEmbeddingService()
    service._embed_fn = fn  # already "loaded": no model download in unit tests
    return service


def test_texts_are_embedded_in_small_batches_to_cap_memory():
    fn = _RecordingFn()
    _service(fn).embed(["x"] * 28)  # the size of the knowledge base: what auto-seed sends

    assert max(fn.batch_sizes) <= OnnxEmbeddingService._BATCH_SIZE
    assert sum(fn.batch_sizes) == 28


def test_batching_preserves_order_and_count():
    texts = ["a", "bb", "ccc", "dddd", "eeeee", "ffffff", "ggggggg"]  # 7 texts -> batches of 4 + 3
    vectors = _service(_RecordingFn()).embed(texts)

    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]
    assert all(isinstance(x, float) for v in vectors for x in v)


def test_empty_input_makes_no_model_call():
    fn = _RecordingFn()
    assert _service(fn).embed([]) == []
    assert fn.batch_sizes == []
