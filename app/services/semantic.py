import asyncio
from dataclasses import dataclass, field
import numpy as np

from app.core.config import settings
from app.core.logger import logger

try:
    from fastembed import TextEmbedding
except ImportError:  # pragma: no cover - optional in minimal test envs
    TextEmbedding = None

try:
    from sklearn.cluster import DBSCAN
except ImportError:  # pragma: no cover - optional in minimal test envs
    DBSCAN = None


_TECH_ISSUE_PROTOTYPES = [
    "stream lag buffering freeze patah patah",
    "suara hilang mute no sound audio error",
    "koneksi putus blackscreen stream mati dc",
]

_CATEGORY_PROTOTYPES: dict[str, list[str]] = {
    "Comedy / Ngakak": [
        "ngakak lucu banget kocak ketawa terbahak bahak",
        "funny hilarious comedy laughing out loud lmao",
        "lawak banget humor receh bikin ngakak",
    ],
    "Shock / Fail": [
        "kaget parah waduh gagal fail blunder fatal",
        "shocking wtf unexpected fail disaster rip",
        "ya ampun gawat mati kena prank panik",
    ],
    "Hype / Clutch": [
        "mantap keren gila clutch win menang gol epic",
        "hype awesome amazing victory goal pog",
        "keren banget gokil juara spektakuler comeback",
    ],
    "Technical Issue": _TECH_ISSUE_PROTOTYPES,
}


@dataclass
class SemanticWindowResult:
    """Result of CPU-based semantic clustering and tech-issue detection for a chat window."""
    convergence_score: float = 0.0
    is_tech_issue: bool = False
    tech_issue_similarity: float = 0.0
    embeddings: np.ndarray | None = field(default=None, repr=False)


class SemanticAnalyzer:
    """
    Lightweight CPU-optimized semantic analyzer using FastEmbed (ONNX Runtime)
    and scikit-learn DBSCAN/cosine similarity. Designed for ARM64/x86 CPUs without GPU.
    """

    def __init__(
        self,
        model_name: str = settings.SEMANTIC_MODEL_NAME,
        enabled: bool = settings.ENABLE_SEMANTIC_ANALYSIS,
        threads: int = 2,
        embedding_model=None,
    ):
        self.model_name = model_name
        self.enabled = enabled
        self.threads = max(1, threads)
        self._model = embedding_model
        self._init_attempted = embedding_model is not None
        self._category_centroids: dict[str, np.ndarray] | None = None

    def _ensure_model(self) -> bool:
        if not self.enabled:
            return False
        if self._model is not None:
            return True
        if self._init_attempted or TextEmbedding is None:
            return False

        self._init_attempted = True
        try:
            self._model = TextEmbedding(model_name=self.model_name, threads=self.threads)
            logger.info(f"Initialized FastEmbed CPU model: {self.model_name} (threads={self.threads})")
            return True
        except Exception as e:
            logger.warning(f"FastEmbed model '{self.model_name}' unavailable ({e}); semantic analysis disabled.")
            self._model = None
            return False

    async def prewarm(self) -> bool:
        """Non-blocking background pre-warm for the ONNX embedding model at startup."""
        if not self.enabled or self._model is not None or self._init_attempted:
            return self._model is not None
        return await asyncio.to_thread(self._ensure_model)

    @staticmethod
    def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0.0, 1.0, norms)
        return matrix / norms

    def _embed(self, texts: list[str]) -> np.ndarray | None:
        if not texts or not self._ensure_model():
            return None
        try:
            vectors = np.asarray(list(self._model.embed(texts)), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] == 0:
                return None
            return self._normalize_rows(vectors)
        except Exception as e:
            logger.warning(f"Semantic embedding failed: {e}")
            return None

    def _get_category_centroids(self) -> dict[str, np.ndarray]:
        if self._category_centroids is not None:
            return self._category_centroids
        centroids: dict[str, np.ndarray] = {}
        for category, prototypes in _CATEGORY_PROTOTYPES.items():
            proto_vecs = self._embed(prototypes)
            if proto_vecs is not None:
                centroids[category] = self._normalize_rows(np.mean(proto_vecs, axis=0, keepdims=True))
        if centroids:
            self._category_centroids = centroids
        return centroids

    def _get_tech_centroid(self) -> np.ndarray | None:
        return self._get_category_centroids().get("Technical Issue")

    def classify_moment(
        self,
        texts: list[str],
        superchat_count: int = 0,
        min_similarity: float = 0.72,
    ) -> str | None:
        """
        Zero-shot semantic moment classifier using cached category prototype centroids.
        Returns None when semantic model is unavailable or no category meets min_similarity.
        """
        cleaned = [
            (t.split(": ", 1)[1] if ": " in t else t).strip()
            for t in texts
            if t and t.strip()
        ]
        if not cleaned:
            return "Support / Donate" if superchat_count >= 2 else None

        centroids = self._get_category_centroids()
        if not centroids:
            return None

        embeddings = self._embed(cleaned[:12])
        if embeddings is None or embeddings.shape[0] == 0:
            return None

        window_centroid = self._normalize_rows(np.mean(embeddings, axis=0, keepdims=True))
        best_category: str | None = None
        best_sim = -1.0
        for category, centroid in centroids.items():
            sim = float((window_centroid @ centroid.T)[0, 0])
            if sim > best_sim:
                best_sim = sim
                best_category = category

        if best_sim >= min_similarity and best_category is not None:
            return best_category
        if superchat_count >= 2:
            return "Support / Donate"
        return None

    def analyze_window(self, texts: list[str]) -> SemanticWindowResult:
        """
        Computes semantic convergence (whether chat messages focus on a shared event)
        and checks if the burst is actually a technical-issue complaint (lag/mute/etc.).
        """
        clean_texts = [t.strip() for t in texts if t and len(t.strip()) >= 2][:40]
        if len(clean_texts) < 3:
            return SemanticWindowResult()

        # Embed only unique strings to save CPU, then map back to preserve true density
        unique_texts: list[str] = []
        index_by_text: dict[str, int] = {}
        row_indices: list[int] = []
        for t in clean_texts:
            idx = index_by_text.get(t)
            if idx is None:
                idx = len(unique_texts)
                index_by_text[t] = idx
                unique_texts.append(t)
            row_indices.append(idx)

        unique_embeddings = self._embed(unique_texts)
        if unique_embeddings is None or unique_embeddings.shape[0] == 0:
            return SemanticWindowResult()
        embeddings = unique_embeddings[row_indices]
        if embeddings.shape[0] < 3:
            return SemanticWindowResult()

        # Pairwise cosine similarity (embeddings are L2-normalized) + largest DBSCAN cluster ratio
        sim_matrix = embeddings @ embeddings.T
        n = sim_matrix.shape[0]
        off_diag_sum = float(np.sum(sim_matrix) - np.trace(sim_matrix))
        mean_sim = max(0.0, off_diag_sum / max(1, n * (n - 1)))

        cluster_ratio = 0.0
        if DBSCAN is not None:
            dist_matrix = np.clip(1.0 - sim_matrix, 0.0, 2.0)
            labels = DBSCAN(eps=0.35, min_samples=3, metric="precomputed").fit_predict(dist_matrix)
            non_noise = [int(lbl) for lbl in labels if lbl != -1]
            if non_noise:
                largest_cluster = max(non_noise.count(lbl) for lbl in set(non_noise))
                cluster_ratio = largest_cluster / n

        convergence = round(min(1.0, max(0.0, 0.55 * mean_sim + 0.45 * cluster_ratio)), 4)

        tech_sim = 0.0
        is_tech_issue = False
        tech_centroid = self._get_tech_centroid()
        if tech_centroid is not None:
            window_centroid = self._normalize_rows(np.mean(embeddings, axis=0, keepdims=True))
            tech_sim = float((window_centroid @ tech_centroid.T)[0, 0])
            is_tech_issue = tech_sim >= 0.72

        return SemanticWindowResult(
            convergence_score=convergence,
            is_tech_issue=is_tech_issue,
            tech_issue_similarity=round(tech_sim, 4),
            embeddings=embeddings,
        )

    def select_diverse_samples_mmr(
        self,
        samples: list[str],
        limit: int = 5,
        lambda_mult: float = 0.65,
    ) -> list[str]:
        """
        Re-orders candidate sample messages using Maximal Marginal Relevance (MMR)
        so selected quotes are both representative and semantically diverse.
        """
        if len(samples) <= 1 or limit <= 1:
            return samples[:limit]

        embeddings = self._embed(samples)
        if embeddings is None or embeddings.shape[0] != len(samples):
            return samples[:limit]

        centroid = self._normalize_rows(np.mean(embeddings, axis=0, keepdims=True))
        relevance = (embeddings @ centroid.T).ravel()
        sim_matrix = embeddings @ embeddings.T

        selected_indices: list[int] = [int(np.argmax(relevance))]
        remaining = [i for i in range(len(samples)) if i != selected_indices[0]]

        while remaining and len(selected_indices) < min(limit, len(samples)):
            best_idx = remaining[0]
            best_score = -1e9
            for idx in remaining:
                redundancy = max(float(sim_matrix[idx, s]) for s in selected_indices)
                mmr_score = lambda_mult * float(relevance[idx]) - (1.0 - lambda_mult) * redundancy
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx
            selected_indices.append(best_idx)
            remaining.remove(best_idx)

        return [samples[i] for i in selected_indices]


_DEFAULT_SEMANTIC_ANALYZER: SemanticAnalyzer | None = None


def get_semantic_analyzer() -> SemanticAnalyzer:
    """Returns the singleton SemanticAnalyzer instance."""
    global _DEFAULT_SEMANTIC_ANALYZER
    if _DEFAULT_SEMANTIC_ANALYZER is None:
        _DEFAULT_SEMANTIC_ANALYZER = SemanticAnalyzer()
    return _DEFAULT_SEMANTIC_ANALYZER
