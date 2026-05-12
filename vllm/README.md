# vLLM — Qwen3-32B-AWQ on RTX 5090

Serves **Qwen/Qwen3-32B-AWQ** (Apache 2.0, 119-language pretraining, BFCL ~75.7%)
on the local RTX 5090 via the OpenAI-compatible vLLM API at `http://localhost:8000/v1`.

## Why this model

- **Tool calling**: top-tier open-weight (BFCL #2) — important for the LangChain agent.
- **Multilingual**: strong Uzbek / Russian / English / Cyrillic-Uzbek coverage.
- **Fits**: ~17 GB AWQ weights + KV cache (fp8) + 32K context comfortably under 32 GB,
  leaving headroom for BGE-M3 to coexist on the same GPU.

## VRAM budget (RTX 5090, 32 GB)

| Component                    | VRAM       |
| ---------------------------- | ---------- |
| Qwen3-32B-AWQ weights         | ~17 GB     |
| KV cache (fp8, 32K ctx)       | ~6 GB      |
| Activations / framework       | ~2 GB      |
| BGE-M3 (in main app process)  | ~2 GB      |
| **Total**                    | **~27 GB** |

`gpu-memory-utilization 0.85` reserves the rest of the card for BGE-M3 plus the
desktop compositor (~600 MB Xorg).

## Start

```bash
cd vllm
./start.sh
# first boot pulls the cu130-nightly image and downloads ~17 GB of weights
docker compose logs -f       # watch startup
curl http://localhost:8000/health
```

Stop with `docker compose down`. The HF weight cache is reused from
`~/.cache/huggingface`, so subsequent starts are fast.

## Wire into the app

`core/llm.py` now supports `LLM_PROVIDER=vllm`. In the project root `.env`:

```
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_MODEL=qwen3-32b
VLLM_API_KEY=EMPTY
```

`VLLM_API_KEY` can be any non-empty string — vLLM doesn't validate it unless
you launch it with `--api-key`.

## Notes on Qwen3 thinking mode

Qwen3 enables a `<think>...</think>` reasoning block by default. For this app
(tool-calling agent, low-temp stat reporting) thinking is disabled per-call via
`extra_body={"chat_template_kwargs": {"enable_thinking": False}}` in
`core/llm.py`. This avoids the reasoning text leaking into tool-call parsing
and roughly halves latency.

If you ever want to re-enable thinking, drop the `extra_body` line in `llm.py`.

## Tweaks

- **Bigger context**: change `--max-model-len` to up to 131072 and add YaRN:
  `--rope-scaling '{"rope_type":"yarn","factor":4.0,"original_max_position_embeddings":32768}'`.
- **Throughput**: bump `--gpu-memory-utilization` to 0.92 if you move BGE-M3 to CPU.
- **Different model**: edit `--model` and `--served-model-name` in
  `docker-compose.yml`. AWQ-quantized variants on HF: `Qwen/Qwen3-32B-AWQ`,
  `Qwen/Qwen3-14B-AWQ`, `Qwen/Qwen3-30B-A3B` (MoE).

## Image tag

Uses `vllm/vllm-openai:cu130-nightly` — RTX 5090 (Blackwell, sm_120) needs
CUDA 13. Stable `:latest` builds against CUDA 12 and won't initialize.
Switch back to `:latest` whenever vLLM cuts a stable CUDA-13 release.
