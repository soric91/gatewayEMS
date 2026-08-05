from typing import List, Optional
from influxdb_client import Point
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api_async import WriteApiAsync
from src.Database.connection import InfluxDBConnection
from src.Utils.logging import get_logger
from dataclasses import dataclass, field


logger = get_logger(__name__)

@dataclass
class InfluxDBRepository:

    _connection: InfluxDBConnection = field(default_factory=InfluxDBConnection)
    _write_api: Optional[WriteApiAsync] = None

    async def initialize(self) -> None:
        """
        Inicializa la conexión async.
        """
        await self._connection.connect()
        self._write_api = self._connection.get_write_api()

        if not self._write_api:
            logger.error("Failed to initialize InfluxDB write API.")
            raise ConnectionError("InfluxDB write API is not available.")

        logger.info("InfluxDBRepository initialized successfully.")


    async def save_points(self, points: List[Point]) -> None:
        """
        Guarda una lista de puntos en InfluxDB.

        El write es `await`: la petición HTTP viaja por aiohttp y cede el
        event loop mientras espera la respuesta, así que la lectura Modbus y
        la publicación MQTT siguen corriendo durante la escritura.
        """
        try:
            await self._write_api.write(
                bucket=self._connection.bucket,
                org=self._connection.org,
                record=points,
            )
            logger.info(f"Successfully saved {len(points)} points to InfluxDB.")
        except InfluxDBError as e:
            logger.error(f"Failed to save points to InfluxDB: {e}")
            raise

    async def shutdown(self) -> None:
        """
        Cierra la conexión a InfluxDB.

        Pasos:
        1. Suelta el write API (WriteApiAsync no mantiene buffer propio:
           cada write() ya viajó al servidor antes de retornar)
        2. Cierra la sesión aiohttp del cliente
        3. Limpia referencias
        """
        try:
            self._write_api = None

            await self._connection.disconnect()

            logger.info("✅ InfluxDBRepository cerrado limpiamente")

        except Exception as e:
            logger.error(f"❌ Error cerrando InfluxDBRepository: {e}")
            raise
