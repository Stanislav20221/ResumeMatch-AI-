"""Real FAISS test; skipped only where optional faiss-cpu cannot be installed."""
import numpy as np
import pytest


def test_real_faiss_indexflatip_cosine():
    faiss = pytest.importorskip('faiss')
    vecs = np.asarray([[1., 0.], [0., 1.], [1., 1.]], dtype=np.float32)
    faiss.normalize_L2(vecs)
    index = faiss.IndexFlatIP(2)
    index.add(vecs)
    sims, ids = index.search(np.asarray([[1., 0.]], dtype=np.float32), 3)
    assert int(ids[0][0]) == 0
    assert float(sims[0][0]) == pytest.approx(1.0)
