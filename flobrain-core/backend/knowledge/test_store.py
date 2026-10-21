import json
import uuid
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings

from knowledge.embeddings import EmbeddingError, FakeEmbedder, HttpEmbedder, get_embedder
from knowledge.store import JsonVectorStore, PgVectorStore, get_store, pgvector_installed


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeEmbedderTests(TestCase):
    def test_deterministic_unit_vectors_of_the_configured_dimension(self):
        emb = FakeEmbedder(dimension=1024)
        a1, a2, b = emb.embed(["alpha", "alpha", "beta"])
        self.assertEqual(len(a1), 1024)
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        self.assertAlmostEqual(sum(v * v for v in a1), 1.0, places=6)
        self.assertEqual(emb.info.model, "fake-embedder")


class HttpEmbedderTests(TestCase):
    def _client(self, dimension=4):
        return HttpEmbedder("https://embed.example", "bge-m3", dimension, api_key="sk-test-xxx")

    def test_sends_openai_shape_and_reads_vectors_in_index_order(self):
        body = _Body({"data": [{"index": 1, "embedding": [0, 0, 1, 0]}, {"index": 0, "embedding": [1, 0, 0, 0]}]})
        with patch("urllib.request.urlopen", return_value=body) as opened:
            vectors = self._client().embed(["first", "second"])
        self.assertEqual(vectors, [[1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://embed.example/v1/embeddings")
        self.assertEqual(json.loads(request.data.decode()), {"model": "bge-m3", "input": ["first", "second"]})
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test-xxx")

    def test_wrong_dimension_is_rejected(self):
        body = _Body({"data": [{"index": 0, "embedding": [1, 0, 0]}]})
        with patch("urllib.request.urlopen", return_value=body):
            with self.assertRaises(EmbeddingError) as ctx:
                self._client(dimension=4).embed(["x"])
        self.assertEqual(ctx.exception.code, "dimension_mismatch")

    def test_count_mismatch_is_rejected(self):
        body = _Body({"data": [{"index": 0, "embedding": [1, 0, 0, 0]}]})
        with patch("urllib.request.urlopen", return_value=body):
            with self.assertRaises(EmbeddingError) as ctx:
                self._client().embed(["a", "b"])
        self.assertEqual(ctx.exception.code, "provider_error")

    def test_http_errors_map_to_codes(self):
        import urllib.error

        for status, code in ((401, "invalid_credential"), (429, "rate_limited"), (400, "provider_rejected"), (503, "provider_unavailable")):
            err = urllib.error.HTTPError("https://embed.example", status, "x", {}, None)
            with patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(EmbeddingError) as ctx:
                    self._client().embed(["a"])
            self.assertEqual(ctx.exception.code, code)

    def test_too_many_inputs_is_rejected_locally(self):
        with patch("urllib.request.urlopen") as opened:
            with self.assertRaises(EmbeddingError):
                self._client().embed(["x"] * 33)
        opened.assert_not_called()


class GetEmbedderTests(TestCase):
    @override_settings(EMBEDDINGS_BACKEND="", EMBEDDINGS_BASE_URL="https://embed.example", EMBEDDINGS_MODEL="bge-m3")
    def test_unset_backend_is_not_configured(self):
        self.assertIsNone(get_embedder())

    @override_settings(EMBEDDINGS_BACKEND="http", EMBEDDINGS_BASE_URL="", EMBEDDINGS_MODEL="bge-m3")
    def test_http_without_base_url_is_not_configured(self):
        with patch("urllib.request.urlopen") as opened:
            self.assertIsNone(get_embedder())
        opened.assert_not_called()

    @override_settings(EMBEDDINGS_BACKEND="http", EMBEDDINGS_BASE_URL="http://jarvis.example:8000", EMBEDDINGS_MODEL="bge-m3")
    def test_plain_http_to_a_remote_host_is_not_configured(self):
        self.assertIsNone(get_embedder())

    @override_settings(EMBEDDINGS_BACKEND="http", EMBEDDINGS_BASE_URL="https://jarvis.example", EMBEDDINGS_MODEL="bge-m3", EMBEDDINGS_DIMENSION=1024)
    def test_https_config_builds_the_http_client(self):
        emb = get_embedder()
        self.assertIsInstance(emb, HttpEmbedder)
        self.assertEqual((emb.info.model, emb.info.dimension), ("bge-m3", 1024))


class JsonStoreTests(TestCase):
    def test_round_trip_ranks_only_allowed_ids(self):
        store = JsonVectorStore(4)
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        store.upsert(a, [1, 0, 0, 0], "m")
        store.upsert(b, [0.9, 0.1, 0, 0], "m")
        store.upsert(c, [1, 0, 0, 0], "m")
        hits = store.search([1, 0, 0, 0], "m", allowed_chunk_ids=[a, b], k=5)
        self.assertEqual([h[0] for h in hits], [a, b])
        self.assertNotIn(c, [h[0] for h in hits])
        self.assertEqual(store.search([1, 0, 0, 0], "m", allowed_chunk_ids=[]), [])
        store.delete([a])
        self.assertEqual([h[0] for h in store.search([1, 0, 0, 0], "m", [a, b])], [b])

    def test_wrong_dimension_is_refused(self):
        with self.assertRaises(ValueError):
            JsonVectorStore(4).upsert(uuid.uuid4(), [1, 0, 0], "m")

    def test_other_model_vectors_are_not_mixed(self):
        store = JsonVectorStore(4)
        a = uuid.uuid4()
        store.upsert(a, [1, 0, 0, 0], "old-model")
        self.assertEqual(store.search([1, 0, 0, 0], "new-model", [a]), [])


class PgVectorStoreTests(TestCase):
    def setUp(self):
        if not pgvector_installed():
            self.skipTest("pgvector is not installed on this database")

    def test_round_trip_and_filter_before_ranking(self):
        store = PgVectorStore(1024)
        self.assertTrue(store.available())
        emb = FakeEmbedder(dimension=1024)
        va, vb, vc = emb.embed(["alpha", "beta", "gamma"])
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        store.upsert(a, va, "fake-embedder")
        store.upsert(b, vb, "fake-embedder")
        store.upsert(c, va, "fake-embedder")  # identical to a, but not allowed
        hits = store.search(va, "fake-embedder", allowed_chunk_ids=[a, b], k=5)
        self.assertEqual(hits[0][0], a)
        self.assertAlmostEqual(hits[0][1], 1.0, places=4)
        self.assertNotIn(c, [h[0] for h in hits])
        store.delete([a])
        self.assertNotIn(a, [h[0] for h in store.search(va, "fake-embedder", [a, b])])

    def test_wrong_dimension_is_refused(self):
        with self.assertRaises(ValueError):
            PgVectorStore(1024).upsert(uuid.uuid4(), [0.0] * 3, "m")


class GetStoreTests(TestCase):
    @override_settings(KNOWLEDGE_VECTOR_STORE="json")
    def test_json_store_for_dev(self):
        self.assertIsInstance(get_store(1024), JsonVectorStore)

    @override_settings(KNOWLEDGE_VECTOR_STORE="pgvector")
    def test_pgvector_store_only_when_available(self):
        store = get_store(1024)
        if connection.vendor == "postgresql" and pgvector_installed():
            self.assertIsInstance(store, PgVectorStore)
        else:
            self.assertIsNone(store)

    @override_settings(KNOWLEDGE_VECTOR_STORE="pgvector")
    def test_unsupported_dimension_has_no_store(self):
        self.assertIsNone(get_store(1536))
