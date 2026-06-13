"""Nearest-neighbour matching over feature vectors.

Wraps :class:`sklearn.neighbors.NearestNeighbors` and adds a greedy
diversity-aware assignment used by the mosaic generator so the same source image
isn't pasted into every similar tile.
"""

from __future__ import annotations

import numpy as np
from sklearn.neighbors import NearestNeighbors


class FeatureMatcher:
    """Index a bank of source feature vectors and match queries against it.

    Parameters
    ----------
    features:
        ``(N, D)`` array of source vectors.
    weights:
        Optional ``(D,)`` per-dimension weights. Scaling dimensions before the
        Euclidean search is how we make, e.g., mean colour dominate the match.
    """

    def __init__(self, features: np.ndarray, weights: np.ndarray | None = None):
        if features.ndim != 2:
            raise ValueError(f"features must be 2-D, got shape {features.shape}")
        self._features = features.astype(np.float32)
        self._weights = (
            np.ones(features.shape[1], dtype=np.float32)
            if weights is None
            else weights.astype(np.float32)
        )
        self._n = features.shape[0]
        self._nn = NearestNeighbors(
            n_neighbors=min(self._n, 32), algorithm="auto"
        )
        self._nn.fit(self._features * self._weights)

    @property
    def count(self) -> int:
        return self._n

    def query(self, vectors: np.ndarray, k: int = 1) -> np.ndarray:
        """Return ``(M, k)`` indices of the nearest sources for each query row."""
        vectors = np.atleast_2d(vectors).astype(np.float32)
        k = min(k, self._n)
        _, idx = self._nn.kneighbors(vectors * self._weights, n_neighbors=k)
        return idx

    def assign_diverse(
        self,
        targets: np.ndarray,
        *,
        max_uses: int | None = None,
        candidates: int = 16,
    ) -> np.ndarray:
        """Assign one source index per target, discouraging overuse.

        For each target we look at its ``candidates`` nearest sources and pick the
        closest one that hasn't hit ``max_uses`` yet. With ``max_uses=None`` this
        degenerates to plain nearest-neighbour (repeats allowed).

        Returns a ``(M,)`` int array of source indices.
        """
        targets = np.atleast_2d(targets).astype(np.float32)
        k = min(max(candidates, 1), self._n)
        neighbours = self.query(targets, k=k)
        if max_uses is None:
            return neighbours[:, 0]

        uses = np.zeros(self._n, dtype=np.int32)
        out = np.empty(targets.shape[0], dtype=np.int64)
        for i, row in enumerate(neighbours):
            chosen = row[0]
            for cand in row:
                if uses[cand] < max_uses:
                    chosen = cand
                    break
            out[i] = chosen
            uses[chosen] += 1
        return out
