"""Offline smoke test for the REAL installed FAISS; no OpenAI requests."""
from __future__ import annotations
import numpy as np

try:
    import faiss
except ImportError as exc:
    raise SystemExit("FAISS НЕ УСТАНОВЛЕН: python -m pip install -r requirements.txt") from exc

vectors = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0]], dtype=np.float32)
faiss.normalize_L2(vectors)
index = faiss.IndexFlatIP(vectors.shape[1])
index.add(vectors)
query = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
score, ids = index.search(query, 3)
assert int(ids[0, 0]) == 0
assert abs(float(score[0, 0]) - 1.0) < 1e-5
assert index.ntotal == 3
print(f"FAISS REAL SMOKE PASSED: {faiss.__version__}, 3 vectors, cosine ranking OK")
