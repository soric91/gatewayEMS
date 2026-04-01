from src.Database.repository import InfluxDBRepository
from dataclasses import dataclass, field
from typing import  List
from src.Models.model import EnergyPoint, DeviceReadResult
from src.Utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModbusService:
    """
    Solo se encarga de:
    - Recibir resultados de dispositivos
    - Transformarlos en EnergyPoint (modelo de dominio)
    - Decidir qué guardar y cuándo
    - Manejar errores de negocio

    NO sabe cómo se escribe en InfluxDB (eso es el repository).
    NO sabe cómo se leen los registros Modbus (eso es otra capa).
    """
    
    _repository: Optional[InfluxDBRepository] = None
    _initialized: bool = field(default=False, init=False)
    
    def __post_init__(self):
        if self._repository is None:
            self._repository = InfluxDBRepository()
    
    async def initialize(self) -> None:
        """
        Inicializa el servicio.

        """
        await self._repository.initialize()
        self._initialized = True
        logger.info("✅ ModbusService inicializado correctamente")
    
    async def save_batch(self, results: List[DeviceReadResult]) -> None:
        """Procesa y guarda un lote de lecturas."""
        try:
            energy_points = EnergyPoint.batch_from_results(results=results) 
            influx_points = [point.to_influx_point() for point in energy_points]
            
            if influx_points:
                await self._repository.save_points(influx_points)
                logger.info(f"Guardados {len(influx_points)} puntos.")
        except Exception as exc:
            logger.error(f"Error procesando lote de lecturas: {exc}")
            
    async def shutdown(self) -> None:
        """
        Cierra la conexión a InfluxDB limpiamente.
        
        IMPORTANTE: Solo llamar al apagar la aplicación,
        NO entre cada lote de guardado.
        """
        if not self._initialized:
            logger.warning("⚠️ ModbusService no estaba inicializado")
            return
        
        try:
            await self._repository.shutdown()
            self._initialized = False
            logger.info("🛑 ModbusService cerrado limpiamente")
        except Exception as e:
            logger.error(f"❌ Error cerrando ModbusService: {e}")
            raise