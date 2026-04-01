from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
    env_file=(".env.local", ".env"),
        env_ignore_empty=True,
        extra="ignore",
    )

    # InfluxDB settings con valores por defecto para tests
    INFLUXDB_TOKEN: Optional[str] = None
    INFLUXDB_ADMIN_USER: Optional[str] = None
    INFLUXDB_ADMIN_PASSWORD: Optional[str] = None
    INFLUXDB_ORG: Optional[str] = None
    INFLUXDB_BUCKET: Optional[str] = None
    INFLUXDB_RETENTION: Optional[str] = None
    INFLUXDB_URL: Optional[str] = None
    
    def is_influxdb_configured(self) -> bool:
        """Verifica si todas las variables de InfluxDB están configuradas"""
        return all([
            self.INFLUXDB_TOKEN,
            self.INFLUXDB_ADMIN_USER,
            self.INFLUXDB_ADMIN_PASSWORD,
            self.INFLUXDB_ORG,
            self.INFLUXDB_BUCKET,
            self.INFLUXDB_RETENTION,
            self.INFLUXDB_URL
        ])
    
@lru_cache()
def get_settings() -> Settings:
    return Settings()