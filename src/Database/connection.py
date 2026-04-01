
import asyncio
from typing import Optional
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from src.Core.config import get_settings, Settings
from src.Utils.logging import get_logger
from dataclasses import dataclass, field

logger = get_logger(__name__)


@dataclass
class InfluxDBConnection:
    settings: Settings = field(default_factory=get_settings)

    bucket: str = field(init=False, default="")
    org: str = field(init=False, default="")

    _client: Optional[InfluxDBClient] = None
    _write_api: Optional[InfluxDBClient.write_api] = None
    _connected: bool = False
    _influxdb_enabled: bool = field(init=False, default=False)
    
    _max_retries: int = 3
    _retry_delay: int = 3  
    _retry_backoff: int = 2  
    _timeout: int = 10

    def __post_init__(self):
        # Verificar si InfluxDB está configurado
        if not self.settings.is_influxdb_configured():
            logger.warning("⚠️ InfluxDB no está configurado. El sistema funcionará sin persistencia de datos.")
            self._influxdb_enabled = False
            return
        
        self._influxdb_enabled = True
        self._client = InfluxDBClient(
            url=self.settings.INFLUXDB_URL, 
            token=self.settings.INFLUXDB_TOKEN, 
            org=self.settings.INFLUXDB_ORG, 
            timeout=self._timeout * 1000
        )
        logger.info("InfluxDB client initialized successfully.")
        self.bucket = self.settings.INFLUXDB_BUCKET    
        self.org = self.settings.INFLUXDB_ORG
        
    async def connect(self)-> bool:
        """
        Conecta a InfluxDB con retry automático.
        
        Returns:
            bool: True si conexión exitosa o si InfluxDB está deshabilitado
        """
        if not self._influxdb_enabled:
            logger.info("ℹ️ InfluxDB deshabilitado, saltando conexión")
            return True
            
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
        if not self._influxdb_enabled or not self._client:
            return False
            
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
    
    def is_enabled(self) -> bool:
        """Verifica si InfluxDB está habilitado"""
        return self._influxdb_enabled
    
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
        if not self._influxdb_enabled:
            return True
            
        if not self._connected:
            logger.info("Conexión perdida, reconectando...")
            return await self.connect()
        return True
