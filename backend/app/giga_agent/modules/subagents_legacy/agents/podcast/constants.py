CHARACTER_LIMIT = 500_000

# Error messages-related constants
ERROR_MESSAGE_NO_INPUT = "Пожалуйста, предоставьте хотя бы один PDF файл или URL."
ERROR_MESSAGE_NOT_PDF = (
    "Предоставленный файл не является PDF. Пожалуйста, загрузите только PDF файлы."
)
ERROR_MESSAGE_NOT_SUPPORTED_IN_SBER_TTS = (
    "Выбранный язык не поддерживается Sber TTS. Пожалуйста, выберите русский язык."
)
ERROR_MESSAGE_READING_PDF = "Ошибка чтения PDF файла"
ERROR_MESSAGE_TOO_LONG = (
    f"Общий контент слишком длинный. "
    f"Пожалуйста, убедитесь, что объединенный текст из PDF и URL содержит менее "
    f"{CHARACTER_LIMIT:,} символов."
)

# GigaChat API-related constants
GIGACHAT_MODEL = "GigaChat-2-Max"
GIGACHAT_MAX_TOKENS = 16384
GIGACHAT_TEMPERATURE = 0.1
GIGACHAT_SCOPE = "GIGACHAT_API_CORP"

# Sber TTS constants
SBER_AUTH_TOKEN = settings.external.salute_speech
SBER_TTS_RETRY_ATTEMPTS = 3
SBER_TTS_RETRY_DELAY = 5  # in seconds

# Supported languages for Sber TTS (currently only Russian)
SBER_TTS_LANGUAGES = ["Russian"]

# Language mapping for GigaChat responses
GIGACHAT_LANGUAGE_MAPPING = {
    "Russian": "ru",
    "English": "en",  # GigaChat может отвечать на английском
}

# General audio-related constants
SUPPORTED_LANGUAGES = ["Russian"]  # Только русский для Sber TTS

# Jina Reader-related constants
JINA_READER_URL = "https://r.jina.ai/"
JINA_RETRY_ATTEMPTS = 3
JINA_RETRY_DELAY = 5  # in seconds
