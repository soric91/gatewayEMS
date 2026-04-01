from typing import List, Optional
from influxdb_client import InfluxDBClient
from influxdb_client import Point
from influxdb_client.client.exceptions import InfluxDBError
from src.Database.connection import InfluxDBConnection
from src.Utils.logging import get_logger
from dataclasses import dataclass, field


logger = get_logger(__name__)

@dataclass
class InfluxDBRepository:
    
    _connection: InfluxDBConnection = field(default_factory=InfluxDBConnection)
    _write_api: Optional[InfluxDBClient.write_api] = None
    
    async def initialize(self) -> None:
        """
        Inicializa la conexión async.
        Si InfluxDB no está configurado, continúa sin error.
        """
        if not self._connection.is_enabled():
            logger.warning("⚠️ InfluxDB deshabilitado, repositorio en modo sin persistencia")
            return
            
        await self._connection.connect()
        self._write_api = self._connection.get_write_api()
        
        if not self._write_api:
            logger.error("Failed to initialize InfluxDB write API.")
            raise ConnectionError("InfluxDB write API is not available.")
        
        logger.info("InfluxDBRepository initialized successfully.")
            
            
    async def save_points(self, points: List[Point]) -> None:
        """Guarda una lista de puntos en InfluxDB."""
        if not self._connection.is_enabled():
            logger.debug("InfluxDB deshabilitado, saltando guardado de puntos")
            return
            
        if not self._write_api:
            logger.warning("Write API no inicializado, no se pueden guardar puntos")
            return
            
        try:
            self._write_api.write(bucket=self._connection.bucket, org=self._connection.org, record=points)
            logger.info(f"Successfully saved {len(points)} points to InfluxDB.")
        except InfluxDBError as e:
            logger.error(f"Failed to save points to InfluxDB: {e}")
            raise

    async def shutdown(self) -> None:
        """
        Cierra la conexión a InfluxDB.
        
        Pasos:
        1. Cierra el write API si está activo
        2. Desconecta del cliente InfluxDB
        3. Limpia referencias
        """
        if not self._connection.is_enabled():
            logger.debug("InfluxDB deshabilitado, saltando shutdown")
            return
            
        try:          
            if self._write_api:
                try:
                    self._write_api.close()
                    logger.debug("✅ Write API cerrado (flush completado)")
                except Exception as e:
                    logger.warning(f"⚠️ Error cerrando write API: {e}")
                finally:
                    self._write_api = None
        
            await self._connection.disconnect()
            
            logger.info("✅ InfluxDBRepository cerrado limpiamente")
            
        except Exception as e:
            logger.error(f"❌ Error cerrando InfluxDBRepository: {e}")
            raise
