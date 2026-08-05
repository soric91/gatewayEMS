import asyncio
from dataclasses import dataclass, field, asdict
from typing import Optional, Set
from datetime import datetime, time
from src.Modbus.app import ModbusApp
from src.Config.config import ConfigManager
from src.Utils.logging import get_logger
from src.Utils.utils import QueueManager, MQTTManager
from src.Core.watchdog import BaseWatchdog
from src.Models.model import CrmConfigEvent, CrmEvent, NameParamsModbus
from src.Database.service import ModbusService
from src.Core.config import settings
from src.Crm.client import CrmAuthError, CrmClient, CrmError
from src.Crm.applier import ConfigApplier, ConfigInvalida
import logging


logger = get_logger(__name__)

@dataclass
class TaskManager(BaseWatchdog):
    """
    Gestiona las tareas asyncio del sistema
    Hereda de BaseWatchdog para monitorear cambios en config.ini
    """
    config: ConfigManager = field(default_factory=ConfigManager)
    
    mqtt_manager: Optional[MQTTManager] = field(init=False, default=None)
    
    modbus_service: Optional[ModbusService] = field(init=False, default=None) 

    connect: str = field(init=False, default="modbusconnect")
    readstart: str = field(init=False, default="modbusread")
    

    interval: int = field(init=False)
    start_hour: int = field(init=False, default=0)
    stop_hour: int = field(init=False, default=23)

    modbus_app: Optional[ModbusApp] = field(init=False, default=None)
    queue_manager: QueueManager = field(init=False, default_factory=QueueManager)

    # Nombres de los suscriptores del bus de fan-out (uno por sink)
    sub_influx: str = field(init=False, default="influxdb")
    sub_mqtt: str = field(init=False, default="mqtt")

    # Plano de control: aparte del bus de telemetría, y una cola por etapa.
    # `QueueManager` reparte a TODOS sus suscriptores, que es lo que quiere la
    # telemetría (cada sink ve todo) y justo lo que no quiere una tubería:
    # aquí cada mensaje tiene un único destinatario.
    fetch_queue: QueueManager = field(
        init=False, default_factory=lambda: QueueManager(maxsize=50)
    )
    apply_queue: QueueManager = field(
        init=False, default_factory=lambda: QueueManager(maxsize=50)
    )
    sub_worker: str = field(init=False, default="worker")

    crm_client: Optional[CrmClient] = field(init=False, default=None)
    config_applier: ConfigApplier = field(init=False, default_factory=ConfigApplier)


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
            # Registrar los suscriptores ANTES de que empiece a publicarse:
            # publish() sólo entrega a las colas ya registradas.
            self.queue_manager.subscribe(self.sub_influx)
            self.queue_manager.subscribe(self.sub_mqtt)
            self.fetch_queue.subscribe(self.sub_worker)
            self.apply_queue.subscribe(self.sub_worker)

            self.mqtt_manager = MQTTManager()
            await self.mqtt_manager.connect()

            # Plano de control del CRM: la suscripción se registra siempre,
            # y se reaplica sola si el broker se cae.
            self.crm_client = CrmClient()
            await self.mqtt_manager.subscribe(settings.MQTT_TOPIC_CONFIG)
            self.mqtt_manager.on_message(
                settings.MQTT_TOPIC_CONFIG, self._on_crm_event
            )
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
                            

                                # Filtro exacto por sección: los nombres de
                                # dispositivo vienen de fuera y no se pueden
                                # deducir partiéndolos por '_'.
                                filtered_results = [
                                    r for r in results
                                    if r.device_section in self._reading_devices
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

                data = await self.queue_manager.consume(self.sub_influx)

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
    
    
    async def task_publish_mqtt(self):
        logger.info("📡 Tarea de publicación MQTT iniciada")
        try:
            while self._running:
                
                data = await self.queue_manager.consume(self.sub_mqtt)
                if data is None:
                    logger.warning("⚠️ Recibido dato None en la cola, ignorando")
                    continue
                
                try:
                   
                    results = data.get(NameParamsModbus.results, [])
                    topic_modbus_data= settings.MQTT_TOPIC_TLM
                    if not results:
                        logger.warning("⚠️ Recibido dato sin resultados en la cola")
                        continue

                    if not self.mqtt_manager:
                        logger.error("❌ MQTTManager no inicializado, no se puede publicar")
                        continue
                    for result in results:
                        await self.mqtt_manager.publish(topic_modbus_data, result)

                    logger.info(f"✅ Lote publicado por MQTT ({len(results)} lecturas)")

                except Exception as e:
                    logger.error(f"❌ Error publicando lote por MQTT: {e}")

        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de publicación MQTT cancelada")

    # ==================================================================
    # Plano de control: configuración remota desde el CRM
    # ==================================================================

    async def _on_crm_event(self, topic: str, payload) -> None:
        """
        Recibe el aviso del CRM. Valida y encola: ni un byte de I/O aquí.

        Corre dentro del bucle de `listen()`, así que hacer aquí la petición
        HTTP bloquearía la recepción de los mensajes siguientes.
        """
        if not isinstance(payload, dict):
            logger.warning(f"⚠️ Aviso del CRM ilegible en {topic}: {payload!r}")
            return

        try:
            evento = CrmConfigEvent.model_validate(payload)
        except Exception as e:
            logger.warning(f"⚠️ Aviso del CRM con formato inesperado: {e}")
            return

        if evento.gateway_uuid != settings.GATEWAY_UUID:
            logger.warning(
                f"⚠️ Aviso dirigido a otro gateway ({evento.gateway_uuid}), ignorado"
            )
            return

        if evento.event != CrmEvent.config_changed:
            logger.warning(f"⚠️ Evento del CRM no soportado: '{evento.event}'")
            return

        logger.info(
            f"📡 El CRM anuncia configuración nueva "
            f"(versión {(evento.config_version or '?')[:12]}…)"
        )
        await self.fetch_queue.publish(evento.model_dump())

    async def reload_config(self) -> bool:
        """
        Recarga config.ini y los mapas sin reiniciar el proceso.

        Al limpiar `prev_values`, el watchdog ve todos los dispositivos como
        recién cambiados en su siguiente vuelta y los conecta por el camino que
        ya existe, sin duplicar aquí la lógica de conexión.
        """
        logger.info("🔄 Recargando configuración en caliente")
        try:
            async with self._read_lock:
                for device_name in list(self._connected_devices):
                    await self._disconnect_device(device_name)
                self._connected_devices.clear()
                self._reading_devices.clear()

                self.config.reload()

                self.modbus_app.device_configs.clear()
                self.modbus_app.device_maps.clear()
                self.modbus_app.clients = {}

                if not self.modbus_app._load_configs():
                    logger.error("❌ Recarga: no se pudieron cargar las configs")
                    return False

                if not self.modbus_app._load_maps():
                    logger.error("❌ Recarga: no se pudieron cargar los mapas")
                    return False

                self.interval = int(self.config.get_value('MAINMODBUS', 'interval', 1))
                self.start_hour = int(self.config.get_value('MAINMODBUS', 'start_hour', 0))
                self.stop_hour = int(self.config.get_value('MAINMODBUS', 'stop_hour', 23))

                nivel = self.config.get_value('DEFAULT', 'loglevel', fallback='INFO')
                logging.getLogger().setLevel(
                    getattr(logging, str(nivel).upper(), logging.INFO)
                )

                # Fuerza al watchdog a reevaluar y reconectar todo
                self.prev_values.clear()

            logger.info(
                f"✅ Configuración recargada: "
                f"{list(self.modbus_app.device_configs.keys())}, "
                f"intervalo={self.interval}s"
            )
            return True

        except Exception as e:
            logger.exception(f"❌ Error recargando configuración: {e}")
            return False

    async def task_fetch_config(self):
        """Descarga la configuración cuando el CRM avisa (o el heartbeat lo pide)."""
        logger.info("📥 Tarea de descarga de configuración iniciada")
        try:
            while self._running:
                evento = await self.fetch_queue.consume(self.sub_worker)

                try:
                    estado = self.config_applier.load_state()
                    anunciada = (evento or {}).get("config_version")

                    if anunciada and anunciada == estado.get("applied_version"):
                        logger.info(
                            "✅ La versión anunciada ya está aplicada, nada que hacer"
                        )
                        continue

                    config, etag = await self.crm_client.get_config(estado.get("etag"))
                    if config is None:
                        continue

                    await self.apply_queue.publish({"config": config, "etag": etag})

                except CrmAuthError as e:
                    logger.critical(
                        f"🔒 Credencial del gateway rechazada: {e}. "
                        f"El CRM tiene que emitir una nueva."
                    )
                except CrmError as e:
                    logger.error(f"❌ Error descargando la configuración: {e}")
                except Exception as e:
                    logger.exception(f"❌ Error inesperado descargando configuración: {e}")

        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de descarga de configuración cancelada")

    async def task_apply_config(self):
        """Escribe la configuración, recarga y avisa al CRM."""
        logger.info("🛠️ Tarea de aplicación de configuración iniciada")
        try:
            while self._running:
                mensaje = await self.apply_queue.consume(self.sub_worker)
                config = (mensaje or {}).get("config")
                if config is None:
                    continue

                try:
                    self.config_applier.apply(config)

                except ConfigInvalida as e:
                    # No se escribió nada: la configuración vigente sigue viva.
                    logger.error(f"❌ Configuración rechazada, no se aplicó: {e}")
                    await self._publicar_estado(error=f"config_invalida: {e}")
                    continue

                except Exception as e:
                    logger.exception(f"❌ Error escribiendo la configuración: {e}")
                    await self._publicar_estado(error=f"escritura: {e}")
                    continue

                if not await self.reload_config():
                    logger.error("❌ La recarga falló, volviendo a la configuración anterior")
                    if self.config_applier.rollback():
                        await self.reload_config()
                    await self._publicar_estado(error="reload_fallido")
                    continue

                self.config_applier.mark_applied(config, mensaje.get("etag"))

                try:
                    await self.crm_client.acknowledge(config.config_version)
                except CrmError as e:
                    # La configuración está viva; sólo el CRM no se enteró.
                    logger.error(f"❌ No se pudo confirmar la configuración al CRM: {e}")

                await self._publicar_estado()

        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de aplicación de configuración cancelada")

    async def task_heartbeat(self):
        """
        Reporta presencia al CRM y pregunta si hay trabajo.

        Es el camino que funciona con el broker caído: el aviso MQTT acelera,
        esto garantiza.
        """
        intervalo = settings.CRM_HEARTBEAT_SECONDS
        logger.info(f"💓 Tarea de heartbeat iniciada (cada {intervalo}s)")
        try:
            while self._running:
                try:
                    respuesta = await self.crm_client.heartbeat()
                    estado = self.config_applier.load_state()

                    if respuesta.get("config_habilitada") and respuesta.get(
                        "config_version_actual"
                    ) != estado.get("applied_version"):
                        logger.info("📡 El CRM tiene configuración pendiente")
                        await self.fetch_queue.publish(
                            {
                                "event": str(CrmEvent.config_changed),
                                "gateway_uuid": settings.GATEWAY_UUID,
                                "config_version": respuesta.get("config_version_actual"),
                            }
                        )

                except CrmAuthError as e:
                    logger.critical(f"🔒 Credencial rechazada en el heartbeat: {e}")
                except Exception as e:
                    logger.error(f"❌ Heartbeat fallido: {e}")

                await asyncio.sleep(intervalo)

        except asyncio.CancelledError:
            logger.info("⏹️ Tarea de heartbeat cancelada")

    async def _publicar_estado(self, error: Optional[str] = None) -> None:
        """Publica el estado del gateway en el topic de presencia del CRM."""
        if not self.mqtt_manager:
            return

        payload = {
            "gateway_uuid": settings.GATEWAY_UUID,
            "config_version_aplicada": self.config_applier.load_state().get(
                "applied_version"
            ),
            "dispositivos_conectados": sorted(self._connected_devices),
            "dispositivos_leyendo": sorted(self._reading_devices),
        }
        if error:
            payload["error"] = error

        try:
            await self.mqtt_manager.publish(settings.MQTT_TOPIC_STATUS, payload)
        except Exception as e:
            logger.warning(f"⚠️ No se pudo publicar el estado: {e}")

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
            asyncio.create_task(
                self.task_publish_mqtt(),
                name="publish_mqtt"
            ),
        ]

        # El plano de control sólo arranca si sus piezas existen: sin MQTT ni
        # cliente del CRM, el gateway sigue leyendo y guardando con la
        # configuración local, que es lo que no puede dejar de funcionar.
        if self.mqtt_manager and self.crm_client:
            self._tasks += [
                asyncio.create_task(
                    self.mqtt_manager.listen(),
                    name="listen_mqtt"
                ),
                asyncio.create_task(
                    self.task_fetch_config(),
                    name="fetch_config"
                ),
                asyncio.create_task(
                    self.task_apply_config(),
                    name="apply_config"
                ),
                asyncio.create_task(
                    self.task_heartbeat(),
                    name="heartbeat"
                ),
            ]
        else:
            logger.warning(
                "⚠️ Sin MQTT o sin cliente del CRM: el gateway funciona con la "
                "configuración local, sin plano de control remoto"
            )
        
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

        if self.crm_client:
            try:
                await self.crm_client.close()
                logger.info("✅ Sesión HTTP del CRM cerrada")
            except Exception as e:
                logger.error(f"❌ Error cerrando la sesión del CRM: {e}")

        if self.modbus_app:
            await self.modbus_app.shutdown()

        logger.info("✅ Todas las tareas detenidas")
