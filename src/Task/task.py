import asyncio
from dataclasses import dataclass, field
from typing import Optional, Set
from datetime import datetime, time
from src.Modbus.app import ModbusApp
from src.Config.config import ConfigManager
from src.Utils.logging import get_logger
from src.Utils.utils import QueueManager
from src.Core.watchdog import BaseWatchdog
from src.Models.model import NameParamsModbus
from src.Database.service import ModbusService


logger = get_logger(__name__)

@dataclass
class TaskManager(BaseWatchdog):
    """
    Gestiona las tareas asyncio del sistema
    Hereda de BaseWatchdog para monitorear cambios en config.ini
    """
    config: ConfigManager = field(default_factory=ConfigManager)
    
    modbus_service: Optional[ModbusService] = field(init=False, default=None) 

    connect: str = field(init=False, default="modbusconnect")
    readstart: str = field(init=False, default="modbusread")
    

    interval: int = field(init=False)
    start_hour: int = field(init=False, default=0)
    stop_hour: int = field(init=False, default=23)

    modbus_app: Optional[ModbusApp] = field(init=False, default=None)
    queue_manager: QueueManager = field(init=False, default_factory=QueueManager)
    

    _tasks: list = field(init=False, default_factory=list)
    _running: bool = field(init=False, default=False)
    _read_lock : asyncio.Lock = field(init=False)
    

    _connected_devices: Set[str] = field(init=False, default_factory=set)
    _reading_devices: Set[str] = field(init=False, default_factory=set)
    
    def __post_init__(self):
        """Carga configuración inicial"""

        BaseWatchdog.__init__(self, poll_interval=2.0)
        
        self._read_lock = asyncio.Lock()
        self.interval = int(self.config.get_value('MAINMODBUS', 'interval', 1))
        self.start_hour = int(self.config.get_value('MAINMODBUS', 'start_hour', 0))
        self.stop_hour = int(self.config.get_value('MAINMODBUS', 'stop_hour', 23))
        
        logger.info(
            f"TaskManager configurado: intervalo={self.interval}s, "
            f"horario={self.start_hour}:00-{self.stop_hour}:00"
        )

    
    async def on_config_changed(self, device_name: str, connect: bool, readstart: bool):
        logger.info(
            f"📡 Procesando cambio en {device_name}: "
            f"connect={connect}, read={readstart}"
        )

        if connect and readstart:
            if device_name not in self._connected_devices:
                logger.info(f"🔌 Conectando {device_name}...")
                success = await self._connect_device(device_name)
                if success:
                    self._connected_devices.add(device_name)
                else:
                    logger.error(f"❌ No se pudo conectar {device_name}")
                    return
            
            if device_name not in self._reading_devices:
                logger.info(f"📖 Iniciando lectura de {device_name}...")
                self._reading_devices.add(device_name)

        elif connect and not readstart:
            if device_name not in self._connected_devices:
                logger.info(f"🔌 Conectando {device_name} (sin lectura)...")
                success = await self._connect_device(device_name)
                if success:
                    self._connected_devices.add(device_name)

            if device_name in self._reading_devices:
                logger.info(f"⏸️ Deteniendo lectura de {device_name}...")
                self._reading_devices.remove(device_name)
                async with self._read_lock:
                    pass  
        
        elif not connect and readstart:
            logger.warning(
                f"⚠️ No se puede leer sin conexión en {device_name}. "
                f"Forzando {self.readstart} = False"
            )
            self.config.set_device_value(device_name, self.readstart, False)
        
        else:

            if device_name in self._reading_devices:
                logger.info(f"⏸️ Pausando lectura de {device_name} antes de desconectar...")
                self._reading_devices.remove(device_name)
            

            if device_name in self._connected_devices:
                logger.info(f"🔌 Desconectando {device_name}...")
                async with self._read_lock:
                    await self._disconnect_device(device_name)
                self._connected_devices.remove(device_name)
  
    
    async def _connect_device(self, device_name: str) -> bool:
        """Delega la conexión a ModbusApp — TaskManager no sabe cómo se conecta."""
        return await self.modbus_app.connect_device(device_name)

    async def _disconnect_device(self, device_name: str) -> None:
        """Delega la desconexión a ModbusApp — TaskManager no sabe cómo se desconecta."""
        await self.modbus_app.disconnect_device(device_name)
    

    async def initialize(self) -> bool:
        """
        Inicializa ModbusApp y el watchdog
        NO conecta dispositivos - espera a que ModbusConnect=True en config
        """
        try:
          
            self.modbus_app = ModbusApp(self.config)
            
            self.modbus_service = ModbusService()
            await self.modbus_service.initialize()

            if not self.modbus_app._load_configs():
                logger.error("❌ No se pudo cargar configs")
                return False
            

            if not self.modbus_app._load_maps():
                logger.error("❌ No se pudo cargar mapas")
                return False

            self.modbus_app.clients = {}
            

            await self.start()
            
            logger.info(
                "✅ TaskManager inicializado\n"
                "💡 Sistema esperando cambios en config.ini\n"
                f"   Cambia {self.connect} y {self.readstart} a True para activar dispositivos"
            )
            return True
            
        except Exception as e:
            logger.exception(f"❌ Error inicializando TaskManager: {e}")
            logger.error(f"❌ Error conectando a InfluxDB: {e}")
            logger.warning("⚠️ Sistema continuará sin guardado en InfluxDB")
            return False
    
    
    def _is_active_hour(self) -> bool:
        """Verifica si está dentro del horario activo"""
        current = datetime.now().time()
        start = time(self.start_hour, 0)
        stop = time(self.stop_hour, 59, 59)
        
        is_active = start <= current <= stop
        
        if not is_active:
            logger.debug(
                f"⏸️ Fuera de horario activo ({self.start_hour}:00 - {self.stop_hour}:00)"
            )
        
        return is_active
    

    async def task_read_modbus_periodic(self):
        """
        Lee datos Modbus periódicamente y los envía a la cola.
        Solo lee dispositivos que están en _reading_devices.
        Respeta el horario configurado.
        """
        logger.info(f"🔄 Tarea de lectura Modbus iniciada (cada {self.interval}s)")
        
        try:
            while self._running:

                if self._is_active_hour():

                    if len(self._reading_devices) > 0:
                        try:

                            async with self._read_lock:
                                results = await self.modbus_app.read_all()
                            

                                filtered_results = [
                                    r for r in results 
                                    if any(r.device_name == dev or r.device_name.startswith(f"{dev}_") 
                                        for dev in self._reading_devices)
                                ]
                                
                                if filtered_results:
  
                                    await self.queue_manager.publish({
                                        NameParamsModbus.results: filtered_results,
                                        NameParamsModbus.success_count: sum(1 for r in filtered_results if r.success),
                                        NameParamsModbus.total_count: len(filtered_results)
                                    })
                                    
                                    success_count = sum(1 for r in filtered_results if r.success)
                                    total_count = len(filtered_results)
                                    
                                    logger.info(
                                        f"📊 Lectura completada: {success_count}/{total_count} exitosos"
                                    )
                                    

                                    for result in filtered_results:
                                        if result.success:
                                            logger.debug(
                                                f"  ✅ {result.device_name} (slave {result.device_id}): "
                                                f"{len(result.data)} variables"
                                            )
                                        else:
                                            logger.warning(
                                                f"  ❌ {result.device_name} (slave {result.device_id}): "
                                                f"{result.error}"
                                            )
                            
                        except Exception as e:
                            logger.error(f"❌ Error en lectura Modbus: {e}")
                    else:
                        logger.debug("⏸️ No hay dispositivos habilitados para lectura")
                
                else:
                    logger.debug("⏸️ Fuera de horario activo, esperando...")

                await asyncio.sleep(self.interval)
        
        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de lectura Modbus cancelada")
        except Exception as e:
            logger.exception(f"❌ Error crítico en task_read_modbus_periodic: {e}")
    
    async def task_process_queue(self):
        """
        Procesa datos de la cola (guardar en DB, enviar a servidor, etc.)
        """
        logger.info("📤 Tarea de procesamiento de cola iniciada")
        
        try:
            while self._running:

                data = await self.queue_manager.consume()
                
                try:
                    results = data.get(NameParamsModbus.results, [])
                    success_count = data.get(NameParamsModbus.success_count, 0)
                    total_count = data.get(NameParamsModbus.total_count, 0)
                    
                    if not results:
                        logger.warning("⚠️ Recibido dato sin resultados en la cola")
                        continue
                    
                    logger.debug(
                        f"📥 Procesando lote de resultados: {success_count}/{total_count} exitosos"
                    )   
                    if self.modbus_service:
                        await self.modbus_service.save_batch(results)
                        logger.info(f"✅ Lote procesado y guardado en InfluxDB")
                    
                    else:
                        logger.error("❌ ModbusService no inicializado, no se pueden guardar datos")
                
                except Exception as e:
                    logger.error(f"❌ Error procesando datos de cola: {e}\n"
                    f"❌ Error guardando en InfluxDB")
        
        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de procesamiento cancelada")
        except Exception as e:
            logger.exception(f"❌ Error crítico en task_process_queue: {e}")
    
    
    async def start_all_tasks(self):
        """Inicia todas las tareas configuradas"""
        if self._running:
            logger.warning("⚠️ Las tareas ya están en ejecución")
            return
        
        self._running = True
        logger.info("🚀 Iniciando todas las tareas")
        
        self._tasks = [
            asyncio.create_task(
                self.task_read_modbus_periodic(), 
                name="read_modbus"
            ),
            asyncio.create_task(
                self.task_process_queue(), 
                name="process_queue"
            ),
        ]
        
        try:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"❌ Error en ejecución de tareas: {e}")
    
    async def stop_all_tasks(self):
        """Detiene todas las tareas de forma elegante"""
        logger.info("🛑 Deteniendo todas las tareas")
        self._running = False

        await self.stop()
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
                
        if self.modbus_service:
            try:
                await self.modbus_service.shutdown()
                logger.info("✅ InfluxDB desconectado")
            except Exception as e:
                logger.error(f"❌ Error cerrando InfluxDB: {e}")
        
        await asyncio.gather(*self._tasks, return_exceptions=True)

        if self.modbus_app:
            await self.modbus_app.shutdown()
        
        logger.info("✅ Todas las tareas detenidas")