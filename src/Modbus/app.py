import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Any
from datetime import datetime, timezone
from src.Config.config import ConfigManager
from src.Modbus.client import ModbusClientFactory
from src.Modbus.modbusmap import ModbusDeviceMap
from src.Modbus.read import read_registers
from src.Models.model import NameParamsModbus, DeviceReadResult
from src.Utils.logging import get_logger
import uuid

logger = get_logger(__name__)

@dataclass
class ModbusApp:
    """Orquestador principal del sistema Modbus"""
    config: ConfigManager = field(default_factory=ConfigManager)
    

    clients: Dict = field(init=False, default_factory=dict)
    device_maps: Dict[str, ModbusDeviceMap] = field(init=False, default_factory=dict)
    device_configs: Dict = field(init=False, default_factory=dict)
    
    async def initialize(self) -> bool:
        """Inicializa: carga config, mapas y conecta clientes"""
        logger.info("🚀 Inicializando ModbusApp")
        

        if not self._load_configs():
            return False
        

        if not self._load_maps():
            return False
        

        if not await self._connect_clients():
            return False
        
        logger.info(f"✅ Inicializado: {len(self.clients)} clientes, {len(self.device_configs)} dispositivos")
        return True
    
    def _load_configs(self) -> bool:
        """Carga configuraciones desde .ini"""
        try:
            devices_str = self.config.get_value('MAINMODBUS', 'devicesnames', fallback='')
            if not devices_str:
                logger.error("No hay dispositivos en MAINMODBUS.devicesnames")
                return False
            
            for device_name in [d.strip() for d in devices_str.split(',')]:
                config = self.config.get_section_dict(device_name)
                if not config:
                    logger.warning(f"Sin config para {device_name}")
                    continue
                
            
                device_ids = [int(x.strip()) for x in config.get('device_id', '1').split(',')]
                
                self.device_configs[device_name] = {
                    **config,
                    'device_ids': device_ids,
                }
            
            logger.info(f"✅ Configs cargadas: {list(self.device_configs.keys())}")
            return True
            
        except Exception as e:
            logger.exception(f"Error cargando configs: {e}")
            return False
    
    def _load_maps(self) -> bool:
        """Carga mapas Modbus desde JSON"""
        try:
            for device_name, config in self.device_configs.items():
                map_path = config.get('mapfile')
                if not map_path:
                    logger.warning(f"Sin mapfile para {device_name}")
                    continue
                
                # Leer blockreading del config (default True para compatibilidad)
                block_reading_str = config.get('blockreading', 'true').lower()
                block_reading = block_reading_str == 'true'
                
                device_map = ModbusDeviceMap(
                    device_name=device_name,
                    map_file_path=map_path,
                    block_reading=block_reading
                )
                
                logger.info(
                    f"Configuración de lectura para {device_name}: "
                    f"block_reading={block_reading}"
                )
                
                if device_map.load_map():
                    device_map.build_read_blocks()
                    self.device_maps[device_name] = device_map
            
            logger.info(f"✅ Mapas cargados: {list(self.device_maps.keys())}")
            return len(self.device_maps) > 0
            
        except Exception as e:
            logger.exception(f"Error cargando mapas: {e}")
            return False
    

    
    async def connect_device(self, device_name: str) -> bool:
        """
        Conecta un dispositivo específico por nombre.
        Encapsula toda la lógica de factory y configuración.
        """
        try:
            if device_name not in self.device_configs:
                logger.error(f"❌ Dispositivo {device_name} no encontrado en configs")
                return False

            config = self.device_configs[device_name]
            factory_config = {}

            for device_id in config['device_ids']:
                entry_name = f"{device_name}_{device_id}"
                factory_config[entry_name] = {
                    NameParamsModbus.protocol:         config.get('protocol', 'RTU').upper(),
                    NameParamsModbus.serial_port:      config.get('serialport'),
                    NameParamsModbus.host:             config.get('host', '127.0.0.1'),
                    NameParamsModbus.port:             int(config['port']) if config.get('port') else None,
                    NameParamsModbus.baudrate:         int(config['baudrate']) if config.get('baudrate') else None,
                    NameParamsModbus.modbus_function:  int(config.get('modbus_function', 3)),
                    NameParamsModbus.modbus_map_path:  config.get('mapfile'),
                    NameParamsModbus.device_id:        device_id,
                    NameParamsModbus.device_name:      device_name,
                }

            factory = ModbusClientFactory(factory_config)
            new_clients = await factory.start_connection()

            if not new_clients:
                logger.error(f"❌ No se pudo conectar ningún cliente para {device_name}")
                return False

            self.clients.update(new_clients)
            logger.info(f"✅ {device_name} conectado ({len(new_clients)} cliente(s))")
            return True

        except Exception as e:
            logger.exception(f"❌ Error conectando {device_name}: {e}")
            return False
        
    async def disconnect_device(self, device_name: str) -> None:
        """
        Desconecta y elimina los clientes de un dispositivo específico.
        """
        try:
            to_remove = []

            for client_key, client_data in self.clients.items():
                devices = client_data.get(NameParamsModbus.devices, [])
                for device in devices:
                    dev_name = device.get(NameParamsModbus.device_name, '')
                    if dev_name == device_name or dev_name.startswith(f"{device_name}_"):
                        await client_data[NameParamsModbus.client].close()
                        to_remove.append(client_key)
                        break

            for key in to_remove:
                del self.clients[key]

            logger.info(f"🔌 {device_name} desconectado ({len(to_remove)} cliente(s))")

        except Exception as e:
            logger.exception(f"❌ Error desconectando {device_name}: {e}")
    
    async def read_all(self) -> List[DeviceReadResult]:
        """Lee todos los dispositivos y retorna resultados con timestamp"""
        results = []
        timestamp = datetime.now(timezone.utc)
        
      
        for client_key, client_data in self.clients.items():
            client = client_data[NameParamsModbus.client]
            devices = client_data[NameParamsModbus.devices]
            
       
            by_map = {}
            for dev in devices:
                name = dev.get('device_name', dev['device_name'].split('device_id')[0])
                by_map.setdefault(name, []).append(dev)
              
            for device_name, device_list in by_map.items():
                part_name = device_name.split('_')
                device_name = f"{part_name[0]}_{part_name[1]}"  
               
                device_map = self.device_maps.get(device_name)
                if not device_map:
                    continue
                
                addresses, counts = device_map.get_read_params()
                
                device_ids = [d[NameParamsModbus.device_id] for d in device_list]
                func_code = device_list[0].get('modbus_function', 3)
                
                try:
               
                    raw_data = await read_registers(client=client, slave= device_ids, address=addresses, count=counts,function_code= func_code)
                    
                    for device_id, registers in raw_data.items():
                        dev_entry = next((d for d in device_list if d[NameParamsModbus.device_id] == device_id), None)
                        if not dev_entry:
                            continue
                        
                        try:
                            identify_device=self.config.get_value(device_name, NameParamsModbus.identify_device, fallback=f"{device_name}_{device_id}")
                            device_type = self.config.get_value(device_name, NameParamsModbus.device_type, fallback="Unknown")
                            parsed = device_map.parse_raw_data(registers)
        
                            results.append(DeviceReadResult(
                                device_name=dev_entry[NameParamsModbus.device_name],
                                device_id=dev_entry[NameParamsModbus.device_id],
                                identify_device=identify_device, 
                                timestamp=timestamp,
                                device_type=device_type,
                                data=parsed,
                                success=True
                            ))
                        except Exception as e:
                            results.append(DeviceReadResult(
                                device_name=dev_entry[NameParamsModbus.device_name],
                                device_id=dev_entry[NameParamsModbus.device_id],
                                identify_device=identify_device,
                                timestamp=timestamp,
                                device_type=device_type,
                                data={},
                                success=False,
                                error=str(e)
                            ))
                
                except Exception as e:
                    logger.error(f"Error leyendo {device_name}: {e}")
        
        logger.info(f"📊 Leídos: {len(results)} dispositivos")
        return results
    
    async def shutdown(self):
        """Cierra todas las conexiones"""
        logger.info("🛑 Cerrando conexiones")
        for client_data in self.clients.values():
            await client_data[NameParamsModbus.client].close()