"""Shared BGE-M3 embedder singleton with dense + sparse support."""

import threading

from core.settings import settings
from core.logger import setup_logger

logger = setup_logger(__name__)

_model = None
_lock = threading.Lock()


def _resolve_device() -> str:
    """Resolve the target device: honour settings, fall back gracefully."""
    requested = settings.bge_m3_device.lower()
    if requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def get_embedder():
    """Return the shared BGE-M3 model instance (lazy-loaded, thread-safe)."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from FlagEmbedding import BGEM3FlagModel
                device = _resolve_device()
                logger.info(
                    f"Loading BGE-M3 model: {settings.bge_m3_model} on device={device}"
                )
                _model = BGEM3FlagModel(
                    settings.bge_m3_model,
                    use_fp16=device != "cpu",
                    device=device,
                )
                logger.info(f"BGE-M3 model loaded successfully (device={device})")
    return _model


def encode_dense_sparse(
    texts: list[str],
    batch_size: int = 32,
) -> tuple[list[list[float]], list[dict[int, float]]]:
    """
    Encode a list of texts with BGE-M3, returning dense vectors and sparse weights.

    Returns:
        dense:  list of 1024-dim float vectors
        sparse: list of {token_id: weight} dicts
    """
    model = get_embedder()
    all_dense: list[list[float]] = []
    all_sparse: list[dict[int, float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        output = model.encode(batch, return_dense=True, return_sparse=True)

        for vec in output["dense_vecs"]:
            all_dense.append(vec.tolist())

        for weights in output["lexical_weights"]:
            all_sparse.append({int(k): float(v) for k, v in weights.items()})

    return all_dense, all_sparse


def encode_query(text: str) -> tuple[list[float], dict[int, float]]:
    """Encode a single query string, returning (dense_vec, sparse_weights)."""
    dense_list, sparse_list = encode_dense_sparse([text])
    return dense_list[0], sparse_list[0]
