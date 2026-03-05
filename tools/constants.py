"""Shared constants for SDMX tools."""


class Units:
    DEFAULT = "kishi"
    MILLIONS = "mln so'm"
    BILLIONS = "mlrd. so'm"
    PERCENT = "%"


class Messages:
    DATA_NOT_INITIALIZED = "Error: SDMX data not initialized. Call initialize_sdmx_data first."
    VECTOR_STORE_NOT_INITIALIZED = "Error: RAG vector store not initialized. Call initialize_rag_vectorstore first."
    FILE_NOT_FOUND = "Error: SDMX data file for ID {sdmx_id} not found in local storage"
    INVALID_DATA_FORMAT = "Error: Invalid data format in SDMX file {sdmx_id}"
    DATA_NOT_FOUND = "Ma'lumot topilmadi: SDMX ID {sdmx_id}"
    REGION_NOT_FOUND = "Mintaqa topilmadi: '{region}' uchun SDMX ID {sdmx_id}"
    YEAR_NOT_FOUND = "Yil topilmadi: '{year}'. Mavjud yillar: {years}"
    UNKNOWN_REGION = "Ma'lum emas"
    NATIONAL_DEFAULT = "O'zbekiston Respublikasi"
    NEED_MORE_YEARS = "Kamida 2 yillik ma'lumot kerak. Mavjud: {count} yil"
