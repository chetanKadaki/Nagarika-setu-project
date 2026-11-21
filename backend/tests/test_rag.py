import app.rag as rag


class FakeVectorStore:
    def __init__(self, metadata):
        self.metadata = metadata

    def get(self, *, include):
        assert include == ["metadatas"]
        return {"metadatas": self.metadata}

    def similarity_search(self, _question, *, k):
        assert _question and k == 5
        return []


def test_document_library_deduplicates_chunks_and_ignores_missing_source_ids(monkeypatch):
    monkeypatch.setattr(
        rag,
        "vector_store",
        lambda: FakeVectorStore(
            [
                {"title": "Z Scheme", "source_url": "https://example.test/z", "version": "2", "source_id": "z"},
                {"title": "A Scheme", "source_url": "https://example.test/a", "version": "1", "source_id": "a"},
                {"title": "A Scheme", "source_url": "https://example.test/a", "version": "1", "source_id": "a"},
                {"title": "Unidentified document"},
                None,
            ]
        ),
    )

    documents = rag.list_approved_documents()

    assert [document["title"] for document in documents] == ["A Scheme", "Z Scheme"]
    assert documents[0]["version"] == "1"


def test_assistant_does_not_invent_an_answer_without_retrieved_sources(monkeypatch):
    monkeypatch.setattr(rag, "vector_store", lambda: FakeVectorStore([]))

    answer, sources = rag.ask_assistant("What are the eligibility rules?", "English")

    assert answer == rag.NO_SOURCE_ANSWER
    assert sources == []


def test_engineer_help_uses_the_builtin_work_guide(monkeypatch):
    class UnavailableVectorStore:
        def similarity_search(self, _question, *, k):
            raise AssertionError("Engineer help should not require scheme-document search.")

    monkeypatch.setattr(rag, "vector_store", lambda: UnavailableVectorStore())

    passages = rag.retrieve_passages("How do I track and submit my assigned work?")

    assert passages == [rag.ENGINEER_GUIDANCE_DOCUMENT]
    assert passages[0].metadata["title"] == "CivicAI Engineer Work Guide"
