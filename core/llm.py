from langchain_openai import ChatOpenAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama

from .settings import settings

if settings.llm_provider == "groq":
    llm = ChatGroq(
        model=settings.groq_model,
        temperature=0.7,
        api_key=settings.groq_api_key,
        streaming=False  # Disable streaming for tool use
    )
elif settings.llm_provider == "ollama":
    llm = ChatOllama(
        model=settings.ollama_model,
        temperature=0.7,
        streaming=False  # Disable streaming for tool use
    )
elif settings.llm_provider == "open_router":
    llm = ChatOpenAI(
        base_url=settings.open_router_base_url,
        api_key=settings.open_router_api_key,
        model="meta-llama/llama-3.3-70b-instruct:free",
        streaming=False,  # Disable streaming - required for tool use
        temperature=0.7
    )