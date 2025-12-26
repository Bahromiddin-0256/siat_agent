from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from langchain_core.runnables import RunnableLambda

from .settings import settings


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
                except Exception:
                    pass
            new_tool_calls.append(tc)

    if changed:
        try:
            message.tool_calls = new_tool_calls
        except Exception:
            # If message is immutable, attach via additional_kwargs.
            ak = getattr(message, "additional_kwargs", {}) or {}
            ak["tool_calls"] = new_tool_calls
            message.additional_kwargs = ak

    return message


def _supports_param(cls, param: str) -> bool:
    """Best-effort check whether a constructor supports a given kwarg."""
    import inspect

    try:
        sig = inspect.signature(cls.__init__)
        return param in sig.parameters
    except Exception:
        return False


# Base model selection
if settings.llm_provider == "groq":
    groq_kwargs = {
        "model": settings.groq_model,
        "temperature": 0.7,
        "api_key": settings.groq_api_key,
    }
    if _supports_param(ChatGroq, "streaming"):
        groq_kwargs["streaming"] = False
    _base_llm = ChatGroq(**groq_kwargs)
elif settings.llm_provider == "ollama":
    ollama_kwargs = {
        "model": settings.ollama_model,
        "temperature": 0.7,
    }
    if _supports_param(ChatOllama, "streaming"):
        ollama_kwargs["streaming"] = False
    _base_llm = ChatOllama(**ollama_kwargs)
elif settings.llm_provider == "open_router":
    openai_kwargs = {
        "base_url": settings.open_router_base_url,
        "api_key": settings.open_router_api_key,
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "temperature": 0.7,
    }
    if _supports_param(ChatOpenAI, "streaming"):
        openai_kwargs["streaming"] = False
    _base_llm = ChatOpenAI(**openai_kwargs)
else:
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

# Export a chat model for agent tool-binding.
base_llm = _base_llm

# Optional: a runnable pipeline that sanitizes outputs defensively.
# NOTE: Don't pass this into agent constructors that expect a ChatModel with .bind_tools().
llm = _base_llm | RunnableLambda(_sanitize_tool_call_args)
