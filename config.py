from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_api_url: str = "https://api.deepseek.com/v1"
    
    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    
    # Модели
    embedding_model: str = "deepseek-embedding"
    chat_model: str = "deepseek-chat"
    vector_dimension: int = 384
    
    # Обработка документов
    chunk_size: int = 1000
    chunk_overlap: int = 200
    
    # Логирование
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()