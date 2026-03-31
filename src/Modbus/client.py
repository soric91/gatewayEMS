import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Union, Optional, Set
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from src.Models.model import NameParamsModbus, ProtocolCom
from src.Utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ModbusClientFactory:
    """
    Dataclass for creating and managing Modbus clients agrupados por puerto/IP.
    """
    config_dict: Dict[str, Dict[str, Any]]
    clients: Dict[str, Dict[str, Any]] = field(init=False, default_factory=dict)
    failed_clients: Set[str] = field(init=False, default_factory=set)
    connection_timeout: float = 10.0
    
    async def start_connection(self) -> Dict[str, Dict[str, Any]]:
        """
        Agrupa y conecta clientes Modbus por puerto/IP.
        :return: Diccionario { puerto/IP : { client: ..., devices: [...] } }
        """
        self.clients = {}
        self.failed_clients = set()
        
        for device_name, device_config in self.config_dict.items():
            protocol = device_config.get(NameParamsModbus.protocol)

            client_key = self._get_client_key(device_config, protocol)
            
            if not client_key:
                logger.warning(f"Dispositivo {device_name} sin puerto o IP válido.")
                continue
            

            if client_key in self.failed_clients:
                logger.warning(f"Saltando dispositivo {device_name} - cliente {client_key} marcado como fallido.")
                continue
            
            try:

                if client_key not in self.clients:
                    client = await self._create_and_connect_client(
                        device_name, device_config, protocol, client_key
                    )
                    
                    if client is None:

                        self.failed_clients.add(client_key)
                        continue
                    

                    self.clients[client_key] = {
                        NameParamsModbus.client: client,
                        NameParamsModbus.devices: []
                    }
                    logger.info(f"Cliente creado y conectado para {client_key}")
                
     
                device_info = self._build_device_info(device_name, device_config)
                self.clients[client_key][NameParamsModbus.devices].append(device_info)
                logger.info(f"Dispositivo {device_name} agregado al cliente {client_key}")
                
            except (asyncio.TimeoutError, ModbusException) as e:
                logger.error(f"Error de conexión con {device_name} ({client_key}): {e}")
                self.failed_clients.add(client_key)
            except Exception as e:
                logger.exception(f"Error inesperado con {device_name}: {e}")
                self.failed_clients.add(client_key)
        
        return self.clients
    
    def _get_client_key(self, device_config: Dict[str, Any], protocol: str) -> Optional[str]:
        """Obtiene la clave del cliente según el protocolo."""
        if protocol == ProtocolCom.RTU:
            return device_config.get(NameParamsModbus.serial_port)
        elif protocol == ProtocolCom.TCP:
            return device_config.get(NameParamsModbus.host)
        return None
    
    async def _create_and_connect_client(
        self, 
        device_name: str, 
        device_config: Dict[str, Any], 
        protocol: str, 
        client_key: str
    ) -> Optional[Union[AsyncModbusSerialClient, AsyncModbusTcpClient]]:
        """
        Crea y conecta un cliente Modbus con validación de parámetros.
        
        :return: Cliente conectado o None si falla
        """
        try:
            if protocol == ProtocolCom.RTU:

                baudrate = device_config.get(NameParamsModbus.baudrate)
                if not baudrate:
                    logger.error(f"Falta baudrate para dispositivo RTU {device_name}")
                    return None
                
                client = AsyncModbusSerialClient(
                    port=client_key,
                    baudrate=baudrate,
                )
                
            elif protocol == ProtocolCom.TCP:

                port = device_config.get(NameParamsModbus.port)
                if not port:
                    logger.error(f"Falta port para dispositivo TCP {device_name}")
                    return None
                
                client = AsyncModbusTcpClient(
                    host=client_key,
                    port=port,
                )
            else:
                logger.warning(f"Protocolo '{protocol}' no soportado para {device_name}")
                return None
            

            await asyncio.wait_for(client.connect(), timeout=self.connection_timeout)
            
            if not client.connected:
                error_msg = getattr(client, 'last_error', 'Razón desconocida')
                logger.error(f"Cliente {client_key} no pudo conectarse. Razón: {error_msg}")
                await self._close_connection(client)
                return None
            
            return client
            
        except asyncio.TimeoutError:
            logger.error(f"Timeout al conectar con {client_key} después de {self.connection_timeout}s")
            if 'client' in locals():
                await self._close_connection(client)
            return None
        except Exception as e:
            logger.exception(f"Error al crear cliente para {client_key}: {e}")
            if 'client' in locals():
                await self._close_connection(client)
            return None
    
    def _build_device_info(self, device_name: str, device_config: Dict[str, Any]) -> Dict[str, Any]:
        """Construye el diccionario de información del dispositivo."""

        return {
            NameParamsModbus.device_name: device_name,
            NameParamsModbus.device_id: device_config.get(NameParamsModbus.device_id),
            NameParamsModbus.modbus_function: device_config.get(NameParamsModbus.modbus_function),
            NameParamsModbus.modbus_map_path: device_config.get(NameParamsModbus.modbus_map_path),
        }
    
    async def _close_connection(self, client: Union[AsyncModbusSerialClient, AsyncModbusTcpClient]):
        """Cierra conexión de un cliente individual."""
        if client:
            try:
                await client.close()
                logger.debug("Conexión de cliente cerrada correctamente")
            except Exception as e:
                logger.error(f"No se pudo cerrar la conexión: {e}")
    
    async def close_all_connections(self):
        """Cierra todas las conexiones de clientes activos."""
        for client_key, client_data in self.clients.items():
            logger.info(f"Cerrando conexión para cliente {client_key}")

            client = client_data.get(NameParamsModbus.client)
            if client:
                await self._close_connection(client)
            else:
                logger.warning(f"Cliente {client_key} es None, ya estaba cerrado")
        
        self.clients.clear()
        logger.info("Todas las conexiones cerradas correctamente")
    
    def get_connected_clients_count(self) -> int:
        """Retorna la cantidad de clientes conectados."""
        return len(self.clients)
    
    def get_failed_clients_count(self) -> int:
        """Retorna la cantidad de clientes que fallaron."""
        return len(self.failed_clients)
    
    def get_devices_by_client(self, client_key: str) -> list:
        """Obtiene la lista de dispositivos asociados a un cliente."""

        return self.clients.get(client_key, {}).get(NameParamsModbus.devices, [])