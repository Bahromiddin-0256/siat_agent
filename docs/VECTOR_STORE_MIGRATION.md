# Vector Store Migration

## Summary

All ChromaDB vector stores have been consolidated into a single `vector/` directory for better organization.

## Changes Made

### 1. Directory Structure

**Before**:
```
siat_agent/
├── chroma_db/              # SDMX RAG vector store
├── metadata_chroma_db/     # Metadata RAG vector store
├── tools/
├── core/
└── ...
```

**After**:
```
siat_agent/
├── vector/
│   ├── sdmx_rag/          # SDMX RAG vector store (was chroma_db/)
│   ├── metadata_rag/      # Metadata RAG vector store (was metadata_chroma_db/)
│   └── README.md
├── tools/
├── core/
└── ...
```

### 2. Files Modified

#### `core/settings.py`
```python
# Before
chroma_persist_dir: Path = BASE_DIR / "chroma_db"
metadata_chroma_persist_dir: Path = BASE_DIR / "metadata_chroma_db"

# After
chroma_persist_dir: Path = BASE_DIR / "vector" / "sdmx_rag"
metadata_chroma_persist_dir: Path = BASE_DIR / "vector" / "metadata_rag"
```

#### `.gitignore`

```gitignore
# Before
chroma_db/
metadata_chroma_db/

# After
../vector/
```

### 3. Directories Moved

```bash
mv chroma_db vector/sdmx_rag
mv metadata_chroma_db vector/metadata_rag
```

## Benefits

1. **Better Organization**: All vector stores in one place
2. **Clearer Naming**: `sdmx_rag` and `metadata_rag` are more descriptive
3. **Scalability**: Easy to add new vector stores in the future
4. **Simpler .gitignore**: One rule instead of multiple

## Migration Steps (Already Completed)

1. ✅ Created `vector/` directory
2. ✅ Moved `chroma_db/` → `vector/sdmx_rag/`
3. ✅ Moved `metadata_chroma_db/` → `vector/metadata_rag/`
4. ✅ Updated `core/settings.py`
5. ✅ Updated `.gitignore`
6. ✅ Created `vector/README.md`

## No Action Required

The migration is **automatic and backward compatible**:

- Existing vector stores were moved (not rebuilt)
- All data preserved
- Application will automatically use new paths
- No data loss

## If Vector Stores Are Missing

If you deleted the old directories before running the migration, the vector stores will be automatically rebuilt on next startup:

```python
# Automatic initialization in main.py
initialize_rag_vectorstore(sdmx_tool._json_data)
initialize_metadata_vectorstore()
```

## Testing

Start the application normally:

```bash
python main.py
```

You should see:
```
INFO - RAG vector store initialized successfully!
INFO - Metadata RAG vector store initialized successfully!
```

Vector stores load from the new paths without any issues.

## Rollback (Not Recommended)

If you need to rollback (unlikely):

```bash
mv vector/sdmx_rag chroma_db
mv vector/metadata_rag metadata_chroma_db
rmdir vector
```

Then revert changes in `core/settings.py` and `.gitignore`.

## Future Additions

With this structure, adding new vector stores is easy:

```
vector/
├── sdmx_rag/
├── metadata_rag/
├── <new_store>/         # Easy to add
└── README.md
```

Just add to `core/settings.py`:
```python
new_store_persist_dir: Path = BASE_DIR / "vector" / "new_store"
```

## Related Files

- `core/settings.py` - Path configuration
- `tools/rag_tool.py` - SDMX RAG implementation
- `tools/metadata_rag_tool.py` - Metadata RAG implementation
- `.gitignore` - Git ignore rules
- `vector/README.md` - Vector store documentation

## Date

Migration completed: 2026-01-11
