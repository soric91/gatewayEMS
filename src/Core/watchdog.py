import asyncio
from src.Utils.logging import get_logger
from src.Config.config import ConfigManager
from dataclasses import dataclass, field

logger = get_logger(__name__)


@dataclass
class BaseWatchdog:
    """
    Watchdog simplificado para monitorear cambios en config.ini
    Usa asyncio puro con polling cada X segundos
    """
    config: ConfigManager = field(default_factory=ConfigManager)
    connect: str = field(default="")
    readstart: str = field(default="")

    def __init__(self, poll_interval: float = 2.0):
        """
        Args:
            poll_interval: Intervalo en segundos para verificar cambios (default: 2.0)
        """
        if not self.connect:
            raise ValueError("La clase hija debe definir 'connect'")
        if not self.readstart:
            raise ValueError("La clase hija debe definir 'readstart'")
        self.config = ConfigManager()
        
        self.poll_interval = poll_interval
        self.prev_values = {}  
        self._watchdog_running = False  
        self._task = None
    
    async def start(self):
        """Inicia el monitoreo de cambios en config.ini"""
        if self._watchdog_running:
            logger.warning("Watchdog ya está en ejecución")
            return
        
        self._watchdog_running = True
        logger.info(f"🔍 Watchdog iniciado (polling cada {self.poll_interval}s)")
        
     
        await self._check_and_notify()
        
  
        self._task = asyncio.create_task(self._monitor_loop())
    
    async def stop(self):
        """Detiene el monitoreo de forma elegante"""
        if not self._watchdog_running:
            return
        
        self._watchdog_running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("🔍 Watchdog detenido")
    
    async def _monitor_loop(self):
        """Loop principal de monitoreo"""
        try:
            while self._watchdog_running:
                await asyncio.sleep(self.poll_interval)
                await self._check_and_notify()
        except asyncio.CancelledError:
            logger.debug("Monitor loop cancelado")
        except Exception as e:
            logger.error(f"Error en monitor loop: {e}")
    
    async def _check_and_notify(self):
        """Verifica cambios en config.ini y notifica si hay cambios"""
        try:
            self.config.reload()
            devices = self._get_devices()
            
            if not devices:
                logger.debug("No hay dispositivos configurados en MAINMODBUS.devicesnames")
                return
            
            for device_name in devices:
                if not self.config.config.has_section(device_name):
                    logger.warning(f"Sección no encontrada: {device_name}")
                    continue
                
        
                connect_value = self.config.config.getboolean(
                    device_name, self.connect, fallback=False
                )
                readstart_value = self.config.config.getboolean(
                    device_name, self.readstart, fallback=False
                )
     
                prev_connect, prev_read = self.prev_values.get(device_name, (None, None))
                
                if (connect_value != prev_connect) or (readstart_value != prev_read):
                    logger.info(
                        f"📡 Cambio detectado en {device_name}: "
                        f"{self.connect}={connect_value}, {self.readstart}={readstart_value}"
                    )

                    self.prev_values[device_name] = (connect_value, readstart_value)
                    
  
                    await self.on_config_changed(device_name, connect_value, readstart_value)
        
        except Exception as e:
            logger.error(f"Error verificando config: {e}")
    
    async def on_config_changed(self, device_name: str, connect: bool, readstart: bool):
        """
        Método que deben implementar las clases hijas.
        Se llama cuando se detecta un cambio en las variables.
        
        Args:
            device_name: Nombre del dispositivo
            connect: Valor de ModbusConnect
            readstart: Valor de ModbusStartRead
        """
        raise NotImplementedError("La clase hija debe implementar on_config_changed")
    
    def _get_devices(self):
        """Obtiene los dispositivos definidos en MAINMODBUS.devicesnames"""
        try:
            devices_raw = self.config.config.get("MAINMODBUS", "devicesnames", fallback="")
            devices = [name.strip() for name in devices_raw.split(",") if name.strip()]
            return devices
        except Exception as e:
            logger.error(f"Error obteniendo dispositivos: {e}")
            return []