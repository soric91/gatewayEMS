
import asyncio
from typing import Optional
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from influxdb_client.client.write_api_async import WriteApiAsync
from src.Core.config import settings
from src.Utils.logging import get_logger
from dataclasses import dataclass, field

logger = get_logger(__name__)

@dataclass
class InfluxDBConnection:
    """
    Conexión a InfluxDB con el cliente ASYNC nativo (aiohttp).

    El cliente síncrono anterior (`InfluxDBClient` + `SYNCHRONOUS`) hacía el
    POST HTTP bloqueando el hilo del event loop: durante cada escritura se
    paraban la lectura Modbus, la publicación MQTT y el watchdog, hasta el
    timeout de 10 s si InfluxDB no respondía.
    """
    _token: str = field(default_factory=lambda: settings.INFLUXDB_TOKEN)
    org: str = field(default_factory=lambda: settings.INFLUXDB_ORG)
    bucket: str = field(default_factory=lambda: settings.INFLUXDB_BUCKET)
    _retention: str = field(default_factory=lambda: settings.INFLUXDB_RETENTION)
    _url: str = field(default_factory=lambda: settings.INFLUXDB_URL)
    _client: Optional[InfluxDBClientAsync] = None
    _write_api: Optional[WriteApiAsync] = None
    _connected: bool = False

    _max_retries: int = 3
    _retry_delay: int = 3
    _retry_backoff: int = 2
    _timeout: int = 10

    @classmethod
    def remota(cls) -> "InfluxDBConnection":
        """
        Conexión al InfluxDB central, con las credenciales INFLUXDB_SERVER_*.

        Misma clase y misma lógica de reintentos que la local: lo único que
        cambia son los valores. `Settings` ya garantiza que están completos
        cuando INFLUXDB_SERVER_ACTIVE está encendido.
        """
        return cls(
            _token=settings.INFLUXDB_SERVER_TOKEN,
            org=settings.INFLUXDB_SERVER_ORG,
            bucket=settings.INFLUXDB_SERVER_BUCKET,
            _retention=settings.INFLUXDB_RETENTION,
            _url=settings.INFLUXDB_SERVER_URL,
        )

    def _build_client(self) -> InfluxDBClientAsync:
        """
        Crea el cliente async. Debe hacerse con el event loop en marcha
        (abre una sesión aiohttp), por eso NO se crea en __post_init__.
        """
        return InfluxDBClientAsync(
            url=self._url,
            token=self._token,
            org=self.org,
            timeout=self._timeout * 1000,  # milisegundos
        )

    async def connect(self) -> bool:
        """
        Conecta a InfluxDB con retry automático.

        Returns:
            bool: True si conexión exitosa
        """
        retries = 0
        while retries < self._max_retries:
            try:
                if self._client is None:
                    self._client = self._build_client()
                    logger.info("InfluxDB async client initialized successfully.")

                if await self._health_check():
                    self._write_api = self._client.write_api()
                    self._connected = True
                    logger.info("Successfully connected to InfluxDB.")
                    return True

                await self._discard_client()
                retries += 1
                if retries < self._max_retries:
                    wait_time = self._retry_delay * (self._retry_backoff ** (retries - 1))
                    logger.warning(f"InfluxDB is unhealthy, retrying connection in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
            except Exception as e:
                logger.error(f"Connection attempt {retries + 1} failed: {e}")
                await self._discard_client()
                retries += 1
                if retries < self._max_retries:
                    await asyncio.sleep(self._retry_delay * (self._retry_backoff ** (retries - 1)))

        logger.critical("Failed to connect to InfluxDB after multiple attempts.")
        raise ConnectionError("Unable to connect to InfluxDB after multiple attempts.")

    async def _discard_client(self) -> None:
        """
        Cierra y descarta el cliente fallido: la sesión aiohttp no se puede
        reutilizar tras un cierre, cada reintento necesita una nueva.
        """
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.debug(f"Error cerrando cliente descartado: {e}")
        self._client = None
        self._write_api = None
        self._connected = False

    async def _health_check(self) -> bool:
        """
        Verifica la salud de InfluxDB.

        Returns:
            bool: True si saludable
        """
        try:
            if await self._client.ping():
                logger.debug("✅ InfluxDB ping: OK")
                return True

            logger.warning("⚠️ InfluxDB unhealthy")
            return False

        except Exception as e:
            # ping() del cliente async propaga la excepción, no devuelve False
            logger.warning(f"⚠️ InfluxDB unhealthy: {e}")
            return False

    async def disconnect(self) -> None:
        """Cierra la conexión"""
        if self._client:
            await self._client.close()
            self._client = None
            self._write_api = None
            self._connected = False
            logger.info("Desconectado de InfluxDB")

    def is_connected(self) -> bool:
        """Verifica si está conectado"""
        return self._connected

    def get_client(self) -> Optional[InfluxDBClientAsync]:
        """Retorna el cliente InfluxDB"""
        return self._client

    def get_write_api(self) -> Optional[WriteApiAsync]:
        """Retorna el write API"""
        return self._write_api

    def get_query_api(self):
        """
        Retorna el query API.

        No se guarda como el de escritura porque no hace falta: `query_api()`
        del cliente async no abre nada, sólo envuelve al cliente.
        """
        return self._client.query_api() if self._client else None

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
