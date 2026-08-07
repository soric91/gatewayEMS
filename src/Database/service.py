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
    
    _repository: InfluxDBRepository = field(default_factory=InfluxDBRepository)
    _initialized: bool = field(default=False, init=False)

    @property
    def repository(self) -> InfluxDBRepository:
        """
        El repositorio local, para quien necesite releer lo ya guardado.

        Lo usa la réplica al servidor central: comparte este cliente en vez de
        abrir un segundo contra el mismo InfluxDB.
        """
        return self._repository


    async def initialize(self) -> None:
        """
        Inicializa el servicio.

        """
        await self._repository.initialize()
        self._initialized = True
        logger.info("✅ ModbusService inicializado correctamente")
    
    async def save_batch(self, results: List[DeviceReadResult]) -> None:
        """Procesa y guarda un lote de lecturas.

        Las lecturas fallidas o sin variables no se guardan: un Point sin
        fields se serializa a cadena vacía (`to_line_protocol() == ''`), así
        que sólo aporta líneas en blanco al cuerpo de la petición y ningún
        dato.
        """
        try:
            guardables = [r for r in results if r.success and r.data]

            descartadas = len(results) - len(guardables)
            if descartadas:
                logger.warning(
                    f"⚠️ {descartadas} lectura(s) sin datos no se guardan en InfluxDB"
                )

            energy_points = EnergyPoint.batch_from_results(results=guardables)
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