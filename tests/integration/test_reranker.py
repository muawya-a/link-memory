"""Opt-in smoke test for the large, locally cached reranker model.

Normal test collection must not require the optional ``sentence-transformers``
runtime or download model weights. To run this check, install the pinned
reranker requirements and set ``LINK_MEMORY_RUN_RERANKER_SMOKE=1``. The model
must already be present in the local Hugging Face cache; this test stays offline.
"""

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("LINK_MEMORY_RUN_RERANKER_SMOKE") != "1",
    reason="set LINK_MEMORY_RUN_RERANKER_SMOKE=1 to run the optional local model smoke test",
)
def test_local_reranker_model_smoke():
    # Set offline flags before importing Hugging Face libraries so this test
    # never downloads model files or emits telemetry.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    torch = pytest.importorskip("torch", reason="install the pinned reranker dependencies")
    sentence_transformers = pytest.importorskip(
        "sentence_transformers", reason="install the pinned reranker dependencies"
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = sentence_transformers.CrossEncoder(
        "Qwen/Qwen3-Reranker-0.6B",
        max_length=512,
        device=device,
        local_files_only=True,
        trust_remote_code=False,
    )
    query = "ما هي تفضيلات معاوية في طريقة الإجابة؟"
    documents = [
        "معاوية يفضل الإجابات المختصرة والواضحة.",
        "تم تشغيل خدمة المعالجة المحلية على الكمبيوتر.",
        "معاوية يريد إجابات طويلة جدًا ومفصلة دائمًا.",
    ]

    ranking = model.rank(query, documents)

    assert len(ranking) == len(documents)
    assert all("corpus_id" in item and "score" in item for item in ranking)
