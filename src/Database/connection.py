
import asyncio
from typing import Optional
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from src.Core.config import settings
from src.Utils.logging import get_logger
from dataclasses import dataclass, field

logger = get_logger(__name__)

@dataclass
class InfluxDBConnection:
    _token: str = field(default_factory=lambda: settings.INFLUXDB_TOKEN)
    org: str = field(default_factory=lambda: settings.INFLUXDB_ORG)
    bucket: str = field(default_factory=lambda: settings.INFLUXDB_BUCKET)
    _retention: str = field(default_factory=lambda: settings.INFLUXDB_RETENTION)
    _url: str = field(default_factory=lambda: settings.INFLUXDB_URL)
    _client: Optional[InfluxDBClient] = None
    _write_api: Optional[InfluxDBClient.write_api] = None
    _connected: bool = False
    
    _max_retries: int = 3
    _retry_delay: int = 3  
    _retry_backoff: int = 2  
    _timeout: int = 10

    def __post_init__(self):
        self._client = InfluxDBClient(url=self._url, token=self._token, org=self.org, timeout=self._timeout * 1000)
        logger.info("InfluxDB client initialized successfully.")    
        
        
    async def connect(self)-> bool:
        """
        Conecta a InfluxDB con retry automático.
        
        Returns:
            bool: True si conexión exitosa
        """
        retries = 0
        while retries < self._max_retries:
            try:
                if await self._health_check():
                    self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
                    self._connected = True
                    logger.info("Successfully connected to InfluxDB.")
                    return True
                else:
                    retries += 1
                    if retries < self._max_retries:
                        wait_time = self._retry_delay * (self._retry_backoff ** (retries - 1))
                        logger.warning(f"InfluxDB is unhealthy, retrying connection in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Connection attempt {retries + 1} failed: {e}")
                retries += 1
                
                await asyncio.sleep(self._retry_delay * (self._retry_backoff ** (retries - 1)))
        
        logger.critical("Failed to connect to InfluxDB after multiple attempts.")
        raise ConnectionError("Unable to connect to InfluxDB after multiple attempts.")
    
    
    async def _health_check(self) -> bool:
        """
        Verifica la salud de InfluxDB.
        
        Returns:
            bool: True si saludable
        """
        try:
            # Usar ping() en lugar de health() (deprecated)
            health = self._client.ping()
            
            if health:
                logger.debug(f"✅ InfluxDB ping: OK")
                return True
            else:
                logger.warning(f"⚠️ InfluxDB unhealthy")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ InfluxDB unhealthy: {e}")
            return False
        
    async def disconnect(self) -> None:
        """Cierra la conexión"""
        if self._client:
            self._client.close()
            self._connected = False
            logger.info("Desconectado de InfluxDB")
    
    def is_connected(self) -> bool:
        """Verifica si está conectado"""
        return self._connected
    
    def get_client(self) -> Optional[InfluxDBClient]:
        """Retorna el cliente InfluxDB"""
        return self._client
    
    def get_write_api(self):
        """Retorna el write API"""
        return self._write_api
    
    async def ensure_connected(self) -> bool:
        """
        Asegura que hay conexión, reconecta si es necesario.
        
        Returns:
            bool: True si conectado
        """
        if not self._connected:
            logger.info("Conexión perdida, reconectando...")
            return await self.connect()
        return True