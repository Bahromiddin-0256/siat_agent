"""Shared BGE-M3 embedder singleton with dense + sparse support."""

import threading

from core.settings import settings
from core.logger import setup_logger

logger = setup_logger(__name__)

_model = None
_lock = threading.Lock()


# BGE-M3 needs ~1 GB on GPU. If less than this is free we'd OOM at .to(device);
# better to fall back to CPU automatically. Common cause: an LLM (Ollama qwen3,
# llama-3.x) is already filling most of the GPU.
_MIN_GPU_FREE_BYTES = 1_500 * 1024 * 1024  # 1.5 GB safety margin


def _cuda_has_free_memory(min_bytes: int) -> bool:
    """True if any visible CUDA device has at least `min_bytes` free."""
    try:
        import torch
        if not torch.cuda.is_available():
            return False
        for i in range(torch.cuda.device_count()):
            try:
                free, _total = torch.cuda.mem_get_info(i)
                if free >= min_bytes:
                    return True
            except (RuntimeError, AttributeError):
                continue
        return False
    except ImportError:
        return False


def _resolve_device() -> str:
    """Resolve the target device: honour settings, fall back gracefully.

    "auto" prefers CUDA → MPS → CPU, but if CUDA is too crowded we fall back
    to CPU silently (with a warning) instead of crashing at model load time.
    Explicit overrides like BGE_M3_DEVICE=cuda still try CUDA — the user is
    responsible for freeing memory in that case.
    """
    requested = settings.bge_m3_device.lower()
    if requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            if _cuda_has_free_memory(_MIN_GPU_FREE_BYTES):
                return "cuda"
            logger.warning(
                "CUDA visible but free memory < %d MB — falling back to CPU. "
                "Free up GPU (e.g. unload Ollama models) or set BGE_M3_DEVICE=cuda "
                "to force the GPU path.",
                _MIN_GPU_FREE_BYTES // (1024 * 1024),
            )
            return "cpu"
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
                # Force fp32. FlagEmbedding's encode() re-runs `self.model.half()`
                # on every call when use_fp16 is True, which on MPS / mixed
                # device setups produces "expected Float but found Half".
                # The fp16 speedup is negligible for this model anyway.
                # NOTE: BGEM3FlagModel uses the plural kwarg `devices=` — passing
                # `device=` silently ends up in **kwargs and is ignored, leaving
                # FlagEmbedding to auto-detect. Use `devices` so our choice wins.
                _model = BGEM3FlagModel(
                    settings.bge_m3_model,
                    use_fp16=False,
                    devices=device,
                )

                # Belt-and-braces: even with use_fp16=False, force every parameter
                # to float32 in case the model was loaded with mixed dtypes.
                try:
                    import torch
                    _model.model.to(dtype=torch.float32)
                except (AttributeError, RuntimeError) as e:
                    logger.debug(f"Could not force float32 cast: {e}")

                logger.info(f"BGE-M3 model loaded successfully (device={device})")
    return _model


def _move_model_to_cpu(model) -> None:
    """Move the BGE-M3 model to CPU and clear CUDA cache (after OOM rescue)."""
    try:
        import torch
        model.model.to("cpu")
        # FlagEmbedding caches target_devices; rewrite so future encode() calls
        # don't try to move it back to a dead GPU.
        try:
            model.target_devices = ["cpu"]
        except (AttributeError, TypeError):
            pass
        model.use_fp16 = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:
        logger.warning(f"Could not move embedder to CPU: {e}")


def encode_dense_sparse(
    texts: list[str],
    batch_size: int = 32,
) -> tuple[list[list[float]], list[dict[int, float]]]:
    """
    Encode a list of texts with BGE-M3, returning dense vectors and sparse weights.

    If the GPU runs out of memory mid-batch (e.g. another process grabbed memory
    after the embedder was loaded), we move the model to CPU once and retry —
    this avoids hard-crashing every subsequent search until the server restarts.

    Returns:
        dense:  list of 1024-dim float vectors
        sparse: list of {token_id: weight} dicts
    """
    model = get_embedder()
    all_dense: list[list[float]] = []
    all_sparse: list[dict[int, float]] = []

    def _encode(batch: list[str]):
        return model.encode(batch, return_dense=True, return_sparse=True)

    cpu_fallback_done = False
    i = 0
    while i < len(texts):
        batch = texts[i : i + batch_size]
        try:
            output = _encode(batch)
        except Exception as e:
            # Catch CUDA OOM (and adjacent device errors) once, recover on CPU,
            # and retry the same batch. Anything else we re-raise.
            err_text = str(e).lower()
            is_cuda_oom = (
                "cuda" in err_text and ("out of memory" in err_text or "allocate" in err_text)
            )
            if is_cuda_oom and not cpu_fallback_done:
                logger.error(
                    "CUDA OOM during encode — moving BGE-M3 to CPU and retrying. "
                    "Future encodes will use CPU until server restart."
                )
                _move_model_to_cpu(model)
                cpu_fallback_done = True
                continue  # retry same batch
            raise

        for vec in output["dense_vecs"]:
            all_dense.append(vec.tolist())

        for weights in output["lexical_weights"]:
            all_sparse.append({int(k): float(v) for k, v in weights.items()})

        i += batch_size

    return all_dense, all_sparse


def encode_query(text: str) -> tuple[list[float], dict[int, float]]:
    """Encode a single query string, returning (dense_vec, sparse_weights)."""
    dense_list, sparse_list = encode_dense_sparse([text])
    return dense_list[0], sparse_list[0]
