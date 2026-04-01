from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_file=(".env.local", ".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    INFLUXDB_TOKEN: str
    INFLUXDB_ADMIN_USER: str
    INFLUXDB_ADMIN_PASSWORD: str
    INFLUXDB_ORG: str
    INFLUXDB_BUCKET: str
    INFLUXDB_RETENTION: str
    INFLUXDB_URL: str
    
@lru_cache()
def get_settings() -> Settings:
    return Settings()