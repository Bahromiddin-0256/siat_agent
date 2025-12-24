# SDMX ID Retriever Agent

An intelligent agent for finding statistical indicator IDs from Uzbekistan's statistics agency using LangChain, LangGraph, and Ollama with RAG (Retrieval-Augmented Generation).

## Features

- **Semantic Search**: RAG-based semantic search using vector embeddings for intelligent matching
- **Keyword Search**: Traditional keyword-based search as fallback
- **Multi-language Support**: Understands English, Russian, and Uzbek
- **LangGraph Agent**: Autonomous agent that can reason and choose the best search strategy
- **Local LLM**: Uses Ollama for privacy and no API costs
- **Interactive Mode**: CLI interface for conversational queries

## Architecture

### Search Methods

1. **RAG Semantic Search** (Primary)
   - Uses vector embeddings (nomic-embed-text)
   - ChromaDB vector store
   - Finds semantically similar indicators
   - Best for natural language questions

2. **Keyword Search** (Fallback)
   - Direct keyword matching
   - Fast and simple
   - Good for specific term searches

3. **LangGraph Agent** (Advanced)
   - Autonomous reasoning with Ollama LLM
   - Chooses best tools for each query
   - Can handle complex multi-step questions

## Installation

### Prerequisites

1. **Python 3.10+**
   ```bash
   python --version
   ```

2. **Ollama**
   - Install from [https://ollama.ai](https://ollama.ai)
   - Start the server:
     ```bash
     ollama serve
     ```

3. **Pull Required Models**
   ```bash
   # Main LLM model (choose one)
   ollama pull llama3.2        # Recommended (default)
   # or
   ollama pull llama3.1        # Larger, more capable
   # or
   ollama pull mistral         # Alternative
   # or
   ollama pull qwen2.5         # Multilingual

   # Embedding model (required for RAG)
   ollama pull nomic-embed-text
   ```

### Install Dependencies

Using pip:
```bash
pip install -e .
```

Or using uv (faster):
```bash
uv pip install -e .
```

### Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` to customize (optional):
   ```bash
   # Ollama Configuration
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=llama3.2
   OLLAMA_EMBEDDING_MODEL=nomic-embed-text
   ```

## Usage

### Web Chat Interface (Recommended)

Start the FastAPI chat server:

```bash
# Option 1: Using the script
./run_server.sh

# Option 2: Using Python directly
python app.py

# Option 3: Using uvicorn
uvicorn app:app --reload --port 8000
```

Then open your browser at `http://localhost:8000` to access the interactive chat interface.

**Features:**
- Modern, responsive web UI
- Real-time chat with WebSocket support
- Fallback to REST API mode
- Example queries for quick start
- Automatic reconnection
- Mobile-friendly design

### REST API Endpoints

Once the server is running, you can also use the API directly:

**POST /chat** - Send a chat message
```bash
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the GDP indicator?"}'
```

**GET /health** - Health check
```bash
curl http://localhost:8000/health
```

**WebSocket /ws** - Real-time chat streaming
```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = (event) => console.log(event.data);
ws.send('Find population indicators');
```

### Command Line Usage

#### Run Demo Examples

```bash
python main.py
```

This will demonstrate:
1. Keyword-based search
2. RAG semantic search
3. LangGraph agent with Ollama

#### Interactive CLI Mode

```bash
python main.py --interactive
```

Interactive commands:
- Just type your question to use the agent
- `keyword <query>` - Force keyword search
- `semantic <query>` - Force semantic search
- `quit` or `exit` - Exit

Example session:
```
Enter your question: What indicators are available for GDP?
[Agent uses semantic search to find relevant indicators]

Enter your question: keyword gross domestic product
[Uses keyword search directly]

Enter your question: semantic economic growth
[Uses RAG semantic search directly]
```

## Code Structure

```
siat_agent/
├── app.py                # FastAPI web server and chat interface
├── agent.py              # LangGraph ReAct agent with Ollama
├── main.py               # CLI entry point and examples
├── run_server.sh         # Script to start the web server
├── static/
│   └── chat.html         # Web chat interface
├── tools/
│   ├── __init__.py
│   ├── sdmx_tool.py      # Keyword-based search tools
│   └── rag_tool.py       # RAG semantic search tools
├── jsons/
│   └── main.json         # SDMX statistical data
├── pyproject.toml        # Dependencies
├── .env.example          # Configuration template
└── README.md             # This file
```

## Development

### Available Tools

The agent has access to these tools:

1. **search_sdmx_semantic** - RAG-based semantic search
2. **search_sdmx_with_score** - Semantic search with relevance scores
3. **get_sdmx_id** - Keyword-based search
4. **get_sdmx_by_code** - Get details for specific code
5. **list_sdmx_categories** - Browse available categories

### Adding New Tools

1. Create tool in `tools/` directory
2. Decorate with `@tool` from `langchain_core.tools`
3. Export in `tools/__init__.py`
4. Add to agent's tool list in `agent.py`

### Customizing the Agent

Edit `agent.py` to:
- Change the model: `model_name="llama3.1"`
- Adjust temperature: `temperature=0.7`
- Modify system prompt for different behavior
- Add/remove tools

## Data Format

The system expects SDMX data in JSON format with this structure:

```json
[
  {
    "id": 1,
    "code": "1.01",
    "name": "Category Name",
    "name_en": "English Name",
    "name_ru": "Russian Name",
    "name_uz": "Uzbek Name",
    "children": [
      {
        "id": 2,
        "code": "1.01.01",
        "name": "Subcategory",
        "period": "Monthly",
        "department": "Department Name",
        "status": "Active"
      }
    ]
  }
]
```

## Troubleshooting

### "Could not connect to Ollama"

1. Check Ollama is running:
   ```bash
   ollama serve
   ```

2. Verify models are pulled:
   ```bash
   ollama list
   ```

3. Test connection:
   ```bash
   curl http://localhost:11434/api/tags
   ```

### "RAG vector store not initialized"

Make sure the JSON data file exists:
```bash
ls jsons/main.json
```

### Slow Performance

- First run is slow (building vector store)
- Subsequent runs use cached embeddings
- Consider using smaller models (llama3.2 vs llama3.1)
- Adjust `k` parameter in search (fewer results = faster)

### Memory Issues

- Use smaller models (llama3.2, phi3)
- Reduce chunk size in RAG
- Limit search results with `k` parameter

## Technologies Used

- **LangChain** (0.3.21+) - Framework for LLM applications
- **LangGraph** (0.2.63+) - Agent orchestration
- **Ollama** - Local LLM inference
- **ChromaDB** (0.5.23+) - Vector database
- **Sentence Transformers** (3.3.1+) - Embeddings
- **nomic-embed-text** - Embedding model

## Performance

- **Keyword Search**: ~50ms
- **Semantic Search**: ~200ms (cached), ~2s (first time)
- **Agent Reasoning**: ~3-10s depending on model and query complexity

## License

This project uses the following open-source components:
- LangChain: MIT License
- Ollama: MIT License
- ChromaDB: Apache 2.0 License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues and questions:
- Check [Ollama Documentation](https://ollama.ai/docs)
- Check [LangChain Documentation](https://python.langchain.com/)
- Review example code in `main.py`
