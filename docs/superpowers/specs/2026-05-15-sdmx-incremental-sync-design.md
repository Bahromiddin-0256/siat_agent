# SDMX katalogni incremental sinxronlash — dizayn hujjati

**Sana:** 2026-05-15
**Holat:** Tasdiqlangan, implementatsiya rejasi tuziladi

## Muammo

`siat.stat.uz` saytidagi SDMX katalogi doimiy yangilanib turadi: yangi indikatorlar qo'shiladi, mavjudlarining xlsx ma'lumotlari yangilanadi, ba'zilari nomi/tasniflari o'zgaradi, ba'zilari `is_active: false` ga o'tkaziladi.

Hozir loyiha (`siat_agent`) `jsons/main.json` va `jsons/sdmxs/<id>.json` fayllarini faqat **birinchi ishga tushganda** yuklab oladi (`main.py` lifespan ichida, `scripts/fetch_sdmx_data.py` orqali). Keyin BGE-M3 bilan embeddinglar qilinib Qdrant kolleksiyasi quriladi. Yangilash mexanizmi yo'q — agent eskirgan ma'lumotlar bilan ishlashda davom etadi.

## Maqsad

Cron, admin endpoint va startup orqali ishga tushadigan incremental sinxronizatsiya yaratish:

- `main.json` ni saytdan yuklab, eskisi bilan diff qilib, faqat o'zgargan elementlarni qayta yuklash
- Vector indeks (Qdrant) — yangi qo'shilgan, metadata o'zgargan, deaktivatsiya qilingan elementlar bo'yicha aniq yangilanish
- Embeddingni faqat zarur bo'lganda chaqirish (BGE-M3 qimmat operatsiya)
- Sync bir vaqtda faqat bitta nusxa ishlashini ta'minlash
- Qisman muvaffaqiyatga toqat qilish (failed IDs keyingi safar qayta uriniladi)

## Tanlangan yondashuv

**Incremental upsert/delete** — to'liq qayta qurish (`rebuild_vectorstore`) o'rniga, har bir o'zgargan ID uchun aniq harakat. To'liq qayta qurish faqat **bootstrap** (`jsons/main.json` yo'q) va **bir martalik migratsiya** (eski sequential point ID schema'dan yangiga) hollarida ishlatiladi.

## Arxitektura

### Modullar

**Yangi:** `core/sdmx_sync.py` — sinxronizatsiya mantig'ining yagona uyi. Asosiy entry:

```python
def sync_sdmx(force_full: bool = False, trigger: str = "manual") -> SyncReport
```

`SyncReport` — dataclass:

```python
@dataclass
class SyncReport:
    skipped: bool = False
    reason: str | None = None       # "already_running" | "bootstrap" | None
    added: list[int] = field(default_factory=list)
    data_only: list[int] = field(default_factory=list)
    metadata: list[int] = field(default_factory=list)
    removed: list[int] = field(default_factory=list)
    inactive: list[int] = field(default_factory=list)
    unchanged: int = 0              # count only, not list
    failed_ids: list[int] = field(default_factory=list)
    duration_s: float = 0.0
    trigger: str = "manual"
```

**Refactor:** `tools/rag_tool.py::initialize_rag_vectorstore` ichidan ikkita helper ajratiladi (extract method — xulq-atvor o'zgarmaydi):

- `_extract_catalog_items(main_json: dict) -> list[tuple[dict, list[str]]]` — DFS o'tib, indekslanadigan elementlarni `(item, path)` shaklida qaytaradi
- `_build_point_for_indicator(item: dict, path: list[str], dense_vec, sparse_vec) -> PointStruct` — bitta indikator uchun Qdrant PointStruct quradi (text + payload + ID)

`sync_sdmx` ham, mavjud `initialize_rag_vectorstore` ham bu helperlarni ishlatadi → ikki kod yo'li bo'lmaydi.

### Entry pointlar

Uchchalasi bitta `sync_sdmx`'ni chaqiradi:

| Trigger | Joy | Xulq |
|---|---|---|
| Cron CLI | `scripts/sync_sdmx.py` (yangi, juda yupqa) | Sinxron chaqiruv, exit code: 0=ok/skipped, 1=fatal, 2=partial |
| Admin endpoint | `main.py`: `POST /admin/sync-sdmx`, `GET /admin/sync-status` | Background task; status keyin pollanadi |
| Startup hook | `main.py` lifespan | `asyncio.create_task(asyncio.to_thread(sync_sdmx, trigger="startup"))` — fon, bloklamaydi |

### Qdrant point ID schemasi (bir martalik migratsiya)

Hozir `tools/rag_tool.py:417` da point ID = `i` (DFS tartibida tartib raqami). Bu incremental upsert/delete uchun yaroqsiz — yangi indikator daraxt o'rtasiga qo'shilsa, undan keyingi hamma point ID siljiydi.

Yangi schema: **point ID = `int(sdmx_id)`**.

`sync_sdmx` boshida tekshiruv:
- Kolleksiyadan bitta point olinadi
- Uning ID si tartib raqami va payload'dagi `id` boshqa son → eski schema → `rebuild_vectorstore` chaqiriladi
- Log: `"Detected old sequential point IDs, performing one-time rebuild"`

## Diff algoritmi

### Katalogni indekslash

`main.json`'da DFS o'tib har bir node uchun `dict[int_id, CatalogEntry]` yig'iladi:

```python
@dataclass
class CatalogEntry:
    id: int
    code: str | None
    is_active: bool
    name: str | None
    name_uz: str | None
    name_en: str | None
    name_ru: str | None
    tags: list[str]
    period: str | None
    department: str | None
    status: str | None
    updated_xlsx: str | None
    path: list[str]
```

Faqat `code` mavjud elementlar diff to'plamlariga kiritiladi (mavjud `initialize_rag_vectorstore` xulq-atvori bilan mos).

### To'plamlarni hisoblash

```
old_ids = old_index.keys()
new_ids = new_index.keys()

added    = new_ids - old_ids               # yangi
removed  = old_ids - new_ids               # main.json'dan yo'q bo'lgan
common   = old_ids & new_ids
```

### `common` ichidagi tasniflash

`EMBEDDING_FIELDS = ("name", "name_uz", "name_en", "name_ru", "tags", "period", "department", "status")` — embedding text'iga kiruvchi maydonlar to'plami. Maydon `"name_uzc"` (Uzbek-Cyrillic) ataylab kiritilmaydi, chunki mavjud `initialize_rag_vectorstore` uni embedding text'iga qo'shmaydi.

**Taqqoslash semantikasi:** skalar maydonlar uchun oddiy `==`. `tags` ro'yxati uchun **sorted set** sifatida taqqoslanadi (`set(old_tags) == set(new_tags)`) — siatda tag tartibi turg'un emas va aks holda biz har sinxronlashda noto'g'ri `metadata` o'zgarishi aniqlardik.

Har bir `id ∈ common` uchun:

1. Agar yangi `is_active` `False` → `inactive` to'plamiga
2. Aks holda, `EMBEDDING_FIELDS`'dagi biror maydon farqli bo'lsa → `metadata`
3. Aks holda, `updated_xlsx` farqli bo'lsa → `data_only`
4. Aks holda → `unchanged` (faqat hisoblanadi)

### Harakat jadvali

| To'plam | sdmxs faylni yuklash | Embedding | Qdrant operatsiya |
|---|---|---|---|
| `added` | Ha | Ha | upsert (yangi point) |
| `metadata` | Ha | Ha | upsert (mavjud point ustiga) |
| `data_only` | Ha | **Yo'q** | `set_payload` (faqat `updated_xlsx`) |
| `inactive` | Yo'q | Yo'q | `delete` (sdmxs fayl saqlanadi) |
| `removed` | Yo'q | Yo'q | `delete` |
| `unchanged` | Yo'q | Yo'q | Yo'q |

**Asosiy optimizatsiya:** odatda siyatda ko'p indikator faqat xlsx jihatdan yangilanadi (oylik/choraklik), nom/tag esa kamdan-kam o'zgaradi. `data_only` yo'l 90%+ holatlarda BGE-M3 embeddingni butunlay o'tkazib yuboradi.

## Sinxronizatsiya oqimi

`sync_sdmx(force_full=False, trigger="manual")` qadamlari:

```
1.  Lock olish — vector/.sync.lock (fcntl.flock LOCK_EX | LOCK_NB)
    └─ Olib bo'lmasa → SyncReport(skipped=True, reason="already_running")

2.  Stale tmp fayllarni tozalash
    └─ jsons/sdmxs/*.tmp va jsons/main.json.new (oldingi crash qoldig'i)

3.  Schema migratsiya tekshiruvi
    └─ Eski sequential point ID aniqlansa → rebuild_vectorstore va exit

4.  Yangi main.json'ni yuklab olish
    └─ URL: settings.sdmx_catalog_url
    └─ Saqlash joyi: jsons/main.json.new
    └─ Yuklash xato → SyncReport(failed_ids=[], reason="catalog_fetch_failed")

5.  Bootstrap tekshiruvi
    └─ jsons/main.json mavjud emas yoki force_full=True bo'lsa
        → initialize_rag_vectorstore(main.json.new)
        → main.json.new -> main.json rename
        → SyncReport(reason="bootstrap")

6.  Diff hisoblash
    └─ old_index = catalog_walk(jsons/main.json)
    └─ new_index = catalog_walk(jsons/main.json.new)
    └─ added, removed, inactive, data_only, metadata, unchanged

7.  Failed IDs'ni qayta urinish to'plamiga qo'shish
    └─ jsons/.sync_failed_ids.json mavjud bo'lsa, undagi IDlarni
       added to'plamiga majburiy qo'shish (qayta urinish).
       Sabab: avvalgi muvaffaqiyatsiz IDning aslida data_only/metadata bo'lganini
       bilmaganimiz uchun, "added" sifatida muomala — to'liq refetch + embed
       + upsert (xavfsiz, lekin bir oz qimmatroq).

8.  Network bosqichi — sdmxs/<id>.json fayllarni yuklab olish
    └─ Yuklash kerak: added ∪ data_only ∪ metadata
    └─ Mavjud fetch_sdmx_data moduli qayta ishlatiladi
       (httpx.AsyncClient + Semaphore(5))
    └─ Vaqtinchalik joy: <id>.json.tmp -> os.replace muvaffaqiyatda
    └─ Xato bo'lgan IDlar diff to'plamlaridan chiqarib tashlanib,
       failed_ids ro'yxatiga qo'shiladi

9.  Vector bosqichi
    a. added ∪ metadata: BGE-M3 batch embedding + Qdrant upsert
       (batch_size=100 ga mos, mavjud upsert pattern bilan)
    b. data_only: Qdrant set_payload (faqat updated_xlsx maydonini yangilash)
    c. inactive ∪ removed: Qdrant delete_points (point ID = int(sdmx_id))

10. Atomik commit
    └─ os.replace(main.json.new, main.json)
    └─ jsons/.sync_failed_ids.json'ni yozish (failed_ids bo'sh bo'lsa o'chirish)

11. Lock'ni qo'yib yuborish

12. SyncReport qaytarish + strukturalangan log yozish
```

### Ketma-ket vs parallel

8 va 9-qadamlar **ketma-ket** bajariladi. Sabab: Qdrant upsert sdmxs faylni o'qimaydi (faqat `main.json` metadata'sini ishlatadi), demak parallel qilish mumkin edi — lekin embedding GPU/CPU intensive va concurrency=5 network'i bilan parallel qilish kichik fayda beradi. Sodda kod va xato boshqaruv ustun.

### Qisman muvaffaqiyat

Failed IDs bo'lsa ham, **muvaffaqiyatli IDlar commit qilinadi** (`main.json` yangilanadi). Failed IDs `jsons/.sync_failed_ids.json` faylda saqlanadi va keyingi sync ularni qayta uradi (7-qadam). Sabab: "all or nothing" yondashuvda bitta indikatorda xato butun sync'ni to'xtatib qo'yadi.

## Atomik holat va crash recovery

### Lock semantikasi

`vector/.sync.lock` faylida `fcntl.flock(LOCK_EX | LOCK_NB)`. Process crash bo'lganda OS lock'ni avtomatik bo'shatadi → stale lock muammosi yo'q.

### Atomik fayl almashtirish

| Fayl | Vaqtinchalik nom | Commit nuqtasi |
|---|---|---|
| `jsons/main.json` | `main.json.new` | 10-qadamda `os.replace()` |
| `jsons/sdmxs/<id>.json` | `<id>.json.tmp` | Har muvaffaqiyatli yuklab olishdan keyin darhol |
| `jsons/.sync_failed_ids.json` | `.sync_failed_ids.json.tmp` | 10-qadamda |

`os.replace()` POSIX'da atomik — yarim yozilgan fayl hech qachon ko'rinmaydi.

### Crash recovery

Sync mid-way crash bo'lganda quyidagi qoldiqlar saqlanishi mumkin:

- `jsons/main.json.new` — yarim yangilangan katalog
- `jsons/sdmxs/<id>.json.tmp` — yarim yuklangan ma'lumot fayllari
- Qdrant'da qisman yangilangan pointlar (bu **xavfsiz**, chunki keyingi sync diff orqali tuzatadi)

Keyingi sync 2-qadamda tmp fayllarni o'chiradi va normal diff bilan davom etadi. 7-qadam `.sync_failed_ids.json` orqali avvalgi muvaffaqiyatsiz IDlarni qaytaradi.

## Kuzatuv

### Strukturalangan log

Har sinxronlash oxirida `logs/sync.log`'ga bitta JSON satr yoziladi:

```json
{
  "ts": "2026-05-15T14:30:00Z",
  "trigger": "cron",
  "duration_s": 12.4,
  "added": 3,
  "data_only": 28,
  "metadata": 1,
  "removed": 0,
  "inactive": 2,
  "unchanged": 1234,
  "failed_ids": [],
  "skipped": false,
  "reason": null
}
```

### Admin endpoint

`GET /admin/sync-status` — eng so'nggi `SyncReport`'ni JSON shaklida qaytaradi. Xotirada saqlanadi (`main.py` modul darajasidagi global), restart'da yo'qoladi. Strukturalangan log doimiy yozuvni saqlaydi.

`POST /admin/sync-sdmx` — `sync_sdmx`'ni background task'da ishga tushiradi. Sotuvchi (caller) `GET /admin/sync-status`'ni pollab kuzatadi.

### Cron uchun exit code

`scripts/sync_sdmx.py`:

| Code | Holat |
|---|---|
| 0 | Muvaffaqiyat yoki `skipped=True` |
| 1 | Fatal xato (catalog fetch failed, bootstrap failed) |
| 2 | Qisman muvaffaqiyat (`failed_ids` non-empty) |

## Test rejasi

### Qo'shimcha qaramliklar

`pyproject.toml`'ga dev-only:
- `pytest>=8.0`
- `pytest-asyncio>=0.23`
- `respx>=0.21` (httpx mock)

### Test qatlamlari

#### Sof birlik testlari — `tests/unit/test_diff.py`

Mock yo'q, faqat dict input → dataclass output:

| Holat | Kutilgan natija |
|---|---|
| Bo'sh `old` | `bootstrap=True` |
| Bir xil kataloglar | hammasi bo'sh, `unchanged` to'lgan |
| Yangi ID qo'shilgan | `added={123}` |
| `updated_xlsx` farqli, qolgan maydonlar bir xil | `data_only={123}` |
| `name_uz` farqli | `metadata={123}` |
| `updated_xlsx` va `name_uz` farqli | `metadata={123}` |
| `is_active: false` ga aylantirilgan | `inactive={123}` |
| ID main.json'dan butunlay yo'q | `removed={123}` |
| Bola tugun o'zgarsa | DFS pastga tushib aniqlanadi |

#### Integratsiya testi — `tests/unit/test_sync_sdmx.py`

`respx`'da `https://api.siat.stat.uz/*`'ni mock qilish, `tmp_path` katalogini ishlatish, Qdrant `:memory:` rejimida. Scenario:

1. `main_v1.json` (3 indikator) bilan boshlang'ich Qdrant state'ni qurish
2. `main_v2.json`'ni mock: 1 added, 1 data_only, 1 metadata
3. `sync_sdmx()` chaqirish
4. Tasdiqlash:
   - Qdrant'da 4 ta point
   - `encode_dense_sparse` faqat 2 marta chaqirilgan (added + metadata)
   - `failed_ids` bo'sh
   - `jsons/main.json` v2'ga almashtirilgan

`tools.embedder.encode_dense_sparse`'ni `monkeypatch` orqali deterministic stub bilan almashtiriladi (real BGE-M3 yuklamaslik uchun).

#### Crash recovery testi

`tmp_path`'da `jsons/sdmxs/123.json.tmp` va `jsons/.sync_failed_ids.json` qo'lda yaratilib, `sync_sdmx()` ishga tushiriladi → tmp o'chirilishi va failed ID qayta urinishi tekshiriladi.

#### Concurrency testi

Ikkita `sync_sdmx()` thread'da bir vaqtda → ikkinchisi `SyncReport(skipped=True, reason="already_running")`.

#### Migration testi

In-memory Qdrant'ga eski schema (sequential ID + payload `id` farqli) joylanadi → `sync_sdmx()` chaqiriladi → `rebuild_vectorstore` ishga tushishi va yangi point ID = `int(sdmx_id)` bo'lishi tekshiriladi.

### Eski testlarni saqlash

Mavjud `tests/test_*.py` smoke skriptlari (real LLM + Qdrant) o'zgartirilmaydi.

### CI

Loyihada CI yo'q. Bu task CI sozlashini kiritmaydi. Testlar `pytest tests/unit/` orqali qo'lda ishga tushiriladi.

## Scope tashqarisidagilar

Quyidagi narsalar bu dizaynga kirmaydi (kelajakda alohida muhokama qilinishi mumkin):

- Webhook/event-based sync (siat API qo'llab-quvvatlamaydi)
- Yo'qotilgan indikatorlar uchun arxiv/tarix
- Real-time invalidation (Qdrant updates streamlash)
- CI/CD pipeline
- Settings.py ga `sdmx_sync_interval` kabi cron interval konfiguratsiyasi (cron ishini host darajasida qiladi)

## O'lchovlar (success criteria)

- Birinchi marta to'liq sync (~3000 indikator) `rebuild_vectorstore` chaqiruvi orqali bir martalik sodir bo'ladi (mavjud yo'l)
- Keyingi incremental sync odatda **< 30 soniya** (0–30 ta indikator o'zgaradi, embedding `metadata` to'plami uchun)
- Sync paytida agentning so'rovlariga javob berish to'xtab qolmaydi (background trigger, Qdrant operatsiyalari atomik)
- Sync mid-way crash bo'lsa keyingi sync avtomatik tuzatadi (manual aralashuvsiz)
