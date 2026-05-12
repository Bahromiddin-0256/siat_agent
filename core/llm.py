from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from langchain_core.runnables import RunnableLambda

from .settings import settings
from .logger import setup_logger

logger = setup_logger(__name__)


def _sanitize_tool_call_args(message):
    """Normalize tool call payloads so AIMessage validation doesn't fail.

    Some providers occasionally return tool_calls where `args` is a list (e.g. a list
    of {question, answer, ...} dicts). LangChain's `AIMessage.tool_calls[*].args`
    must be a dict, so we wrap list args under a stable key.
    """
    tool_calls = getattr(message, "tool_calls", None)
    if not tool_calls:
        return message

    changed = False
    new_tool_calls = []

    for tc in tool_calls:
        # Tool calls are typically dict-like already.
        if isinstance(tc, dict):
            args = tc.get("args")
            if isinstance(args, list):
                # Keep semantics: preserve list exactly under one key.
                tc = {**tc, "args": {"items": args}}
                changed = True
            new_tool_calls.append(tc)
        else:
            # Best-effort for ToolCall objects
            args = getattr(tc, "args", None)
            if isinstance(args, list):
                try:
                    tc.args = {"items": args}
                    changed = True
                except (AttributeError, TypeError) as e:
                    logger.debug(f"Unable to set args on ToolCall object: {e}")
            new_tool_calls.append(tc)

    if changed:
        try:
            message.tool_calls = new_tool_calls
        except (AttributeError, TypeError) as e:
            # If message is immutable, attach via additional_kwargs.
            logger.debug(f"Message tool_calls immutable, using additional_kwargs: {e}")
            ak = getattr(message, "additional_kwargs", {}) or {}
            ak["tool_calls"] = new_tool_calls
            message.additional_kwargs = ak

    return message


def _supports_param(cls, param: str) -> bool:
    """Best-effort check whether a constructor supports a given kwarg."""
    import inspect

    try:
        sig = inspect.signature(cls.__init__)
        if param in sig.parameters:
            return True
        # If **kwargs is accepted, allow the param.
        for p in sig.parameters.values():
            if p.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return False
    except (ValueError, TypeError) as e:
        logger.debug(f"Unable to inspect signature for {cls.__name__}: {e}")
        return False


# Base model selection
logger.info(f"Initializing LLM provider: {settings.llm_provider}")

# Low temperature: this agent reports statistical numbers — determinism matters
# more than creativity.
_TEMPERATURE = 0.4

if settings.llm_provider == "groq":
    groq_kwargs = {
        "model": settings.groq_model,
        "temperature": _TEMPERATURE,
        "api_key": settings.groq_api_key,
    }
    if _supports_param(ChatGroq, "streaming"):
        groq_kwargs["streaming"] = False
    _base_llm = ChatGroq(**groq_kwargs)
    logger.info(f"Groq LLM initialized with model: {settings.groq_model}")
elif settings.llm_provider == "ollama":
    ollama_kwargs = {
        "model": settings.ollama_model,
        "temperature": _TEMPERATURE,
    }
    if _supports_param(ChatOllama, "streaming"):
        ollama_kwargs["streaming"] = False
    _base_llm = ChatOllama(**ollama_kwargs)
    logger.info(f"Ollama LLM initialized with model: {settings.ollama_model}")
elif settings.llm_provider == "open_router":
    openai_kwargs = {
        "base_url": settings.open_router_base_url,
        "api_key": settings.open_router_api_key,
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "temperature": _TEMPERATURE,
    }
    if _supports_param(ChatOpenAI, "streaming"):
        openai_kwargs["streaming"] = False
    _base_llm = ChatOpenAI(**openai_kwargs)
    logger.info("OpenRouter LLM initialized with model: meta-llama/llama-3.3-70b-instruct:free")
elif settings.llm_provider == "deepinfra":
    deepinfra_kwargs = {
        "base_url": settings.deepinfra_base_url,
        "api_key": settings.deepinfra_api_key,
        "model": settings.deepinfra_model,
        "temperature": _TEMPERATURE,
    }
    if _supports_param(ChatOpenAI, "streaming"):
        deepinfra_kwargs["streaming"] = False
    _base_llm = ChatOpenAI(**deepinfra_kwargs)
    logger.info(f"DeepInfra LLM initialized with model: {settings.deepinfra_model}")
elif settings.llm_provider == "vllm":
    # Local vLLM server (OpenAI-compatible). See vllm/ folder for the Docker setup.
    # extra_body disables Qwen3's default <think> reasoning block — it interferes
    # with tool-call parsing and roughly doubles latency for this tool-only agent.
    vllm_kwargs = {
        "base_url": settings.vllm_base_url,
        "api_key": settings.vllm_api_key or "EMPTY",
        "model": settings.vllm_model,
        "temperature": _TEMPERATURE,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    if _supports_param(ChatOpenAI, "streaming"):
        vllm_kwargs["streaming"] = False
    _base_llm = ChatOpenAI(**vllm_kwargs)
    logger.info(f"vLLM initialized at {settings.vllm_base_url} with model: {settings.vllm_model}")
else:
    error_msg = f"Unsupported LLM_PROVIDER: {settings.llm_provider}"
    logger.error(error_msg)
    raise ValueError(error_msg)

# Export a chat model for agent tool-binding.
base_llm = _base_llm

# Optional: a runnable pipeline that sanitizes outputs defensively.
# NOTE: Don't pass this into agent constructors that expect a ChatModel with .bind_tools().
llm = _base_llm | RunnableLambda(_sanitize_tool_call_args)
