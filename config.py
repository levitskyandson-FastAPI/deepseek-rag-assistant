from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # DeepSeek (для генерации ответов)
    deepseek_api_key: str = ""
    deepseek_api_url: str = "https://api.deepseek.com/v1"

    # Yandex Cloud (для эмбеддингов)
    yc_folder_id: str = ""
    yc_api_key: str = ""

    # PostgreSQL (Yandex Cloud Managed Service)
    db_host: str = ""
    db_port: int = 6432
    db_name: str = "db1"
    db_user: str = "user1"
    db_password: str = ""

    # Модели
    embedding_model: str = "text-search-doc"  # для YandexGPT
    chat_model: str = "deepseek-chat"         # оставляем DeepSeek
    vector_dimension: int = 256                # размерность эмбеддингов YandexGPT

    # Обработка документов
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Логирование
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
# Force update for Render