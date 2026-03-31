"""
Unit tests for src/Modbus/client.py

Tests para ModbusClientFactory:
- start_connection(): Creación y conexión de clientes
- Agrupación por puerto/IP
- Manejo de errores y timeouts
- Gestión de clientes fallidos
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.Modbus.client import ModbusClientFactory
from src.Models.model import NameParamsModbus, ProtocolCom


class TestModbusClientFactory:
    """Tests para la clase ModbusClientFactory"""
    
    @pytest.mark.asyncio
    async def test_start_connection_tcp_success(self):
        """✅ Conexión TCP exitosa"""
        config = {
            "device_TCP_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
                NameParamsModbus.modbus_function: 3,
                NameParamsModbus.modbus_map_path: "map.json"
            }
        }
        
        factory = ModbusClientFactory(config)
        
        # Mock del cliente TCP
        mock_tcp_client = AsyncMock()
        mock_tcp_client.connected = True
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client):
            clients = await factory.start_connection()
        
        # Verificar que se creó 1 cliente
        assert len(clients) == 1
        assert "192.168.1.100" in clients
        
        # Verificar estructura del cliente
        client_data = clients["192.168.1.100"]
        assert client_data[NameParamsModbus.client] == mock_tcp_client
        assert len(client_data[NameParamsModbus.devices]) == 1
        
        # Verificar info del dispositivo
        device = client_data[NameParamsModbus.devices][0]
        assert device[NameParamsModbus.device_name] == "device_TCP_1"
        assert device[NameParamsModbus.device_id] == 1
    
    @pytest.mark.asyncio
    async def test_start_connection_rtu_success(self):
        """✅ Conexión RTU (Serial) exitosa"""
        config = {
            "device_RTU_1": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                NameParamsModbus.serial_port: "/dev/ttyUSB0",
                NameParamsModbus.baudrate: 9600,
                NameParamsModbus.device_id: 1,
                NameParamsModbus.modbus_function: 3,
                NameParamsModbus.modbus_map_path: "map.json"
            }
        }
        
        factory = ModbusClientFactory(config)
        
        # Mock del cliente Serial
        mock_serial_client = AsyncMock()
        mock_serial_client.connected = True
        
        with patch('src.Modbus.client.AsyncModbusSerialClient', return_value=mock_serial_client):
            clients = await factory.start_connection()
        
        # Verificar agrupación por puerto serial
        assert len(clients) == 1
        assert "/dev/ttyUSB0" in clients
        assert clients["/dev/ttyUSB0"][NameParamsModbus.client] == mock_serial_client
    
    @pytest.mark.asyncio
    async def test_start_connection_groups_devices_by_port(self):
        """✅ Agrupa múltiples dispositivos en el mismo puerto"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                NameParamsModbus.serial_port: "/dev/ttyUSB0",
                NameParamsModbus.baudrate: 9600,
                NameParamsModbus.device_id: 1,
            },
            "device_2": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                NameParamsModbus.serial_port: "/dev/ttyUSB0",  # Mismo puerto
                NameParamsModbus.baudrate: 9600,
                NameParamsModbus.device_id: 2,
            },
            "device_3": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                NameParamsModbus.serial_port: "/dev/ttyUSB1",  # Diferente puerto
                NameParamsModbus.baudrate: 9600,
                NameParamsModbus.device_id: 3,
            }
        }
        
        factory = ModbusClientFactory(config)
        
        mock_serial_client = AsyncMock()
        mock_serial_client.connected = True
        
        with patch('src.Modbus.client.AsyncModbusSerialClient', return_value=mock_serial_client):
            clients = await factory.start_connection()
        
        # Solo 2 clientes (no 3) porque device_1 y device_2 comparten puerto
        assert len(clients) == 2
        
        # Verificar agrupación en /dev/ttyUSB0
        assert "/dev/ttyUSB0" in clients
        assert len(clients["/dev/ttyUSB0"][NameParamsModbus.devices]) == 2
        
        # Verificar /dev/ttyUSB1
        assert "/dev/ttyUSB1" in clients
        assert len(clients["/dev/ttyUSB1"][NameParamsModbus.devices]) == 1
    
    @pytest.mark.asyncio
    async def test_start_connection_groups_devices_by_host(self):
        """✅ Agrupa múltiples dispositivos TCP en el mismo host"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
            },
            "device_2": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",  # Mismo host
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 2,
            }
        }
        
        factory = ModbusClientFactory(config)
        
        mock_tcp_client = AsyncMock()
        mock_tcp_client.connected = True
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client):
            clients = await factory.start_connection()
        
        # Solo 1 cliente compartido
        assert len(clients) == 1
        assert "192.168.1.100" in clients
        assert len(clients["192.168.1.100"][NameParamsModbus.devices]) == 2
    
    @pytest.mark.asyncio
    async def test_start_connection_tcp_not_connected(self):
        """❌ Cliente TCP conecta pero connected=False"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config)
        
        mock_tcp_client = AsyncMock()
        mock_tcp_client.connected = False  # ❌ No conectó
        mock_tcp_client.last_error = "Connection refused"
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client):
            clients = await factory.start_connection()
        
        # No debe haber clientes conectados
        assert len(clients) == 0
        
        # Debe estar marcado como fallido
        assert len(factory.failed_clients) == 1
        assert "192.168.1.100" in factory.failed_clients
    
    @pytest.mark.asyncio
    async def test_start_connection_timeout(self):
        """❌ Timeout en conexión"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config, connection_timeout=0.1)
        
        mock_tcp_client = AsyncMock()
        
        # Simular conexión lenta (más que el timeout)
        async def slow_connect():
            await asyncio.sleep(1)  # 1 segundo > 0.1 timeout
        
        mock_tcp_client.connect = slow_connect
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client):
            clients = await factory.start_connection()
        
        # Debe fallar por timeout
        assert len(clients) == 0
        assert "192.168.1.100" in factory.failed_clients
    
    @pytest.mark.asyncio
    async def test_start_connection_missing_baudrate_rtu(self):
        """❌ RTU sin baudrate debe fallar"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                NameParamsModbus.serial_port: "/dev/ttyUSB0",
                # ❌ Sin baudrate
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config)
        clients = await factory.start_connection()
        
        # No debe crear clientes
        assert len(clients) == 0
    
    @pytest.mark.asyncio
    async def test_start_connection_missing_port_tcp(self):
        """❌ TCP sin port debe fallar"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                # ❌ Sin port
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config)
        clients = await factory.start_connection()
        
        assert len(clients) == 0
    
    @pytest.mark.asyncio
    async def test_start_connection_missing_serial_port(self):
        """❌ RTU sin serial_port debe ser ignorado"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.RTU,
                # ❌ Sin serial_port
                NameParamsModbus.baudrate: 9600,
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config)
        clients = await factory.start_connection()
        
        assert len(clients) == 0
    
    @pytest.mark.asyncio
    async def test_start_connection_skips_failed_client_key(self):
        """✅ Salta dispositivos si el client_key ya falló"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
            },
            "device_2": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",  # Mismo host que falló
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 2,
            }
        }
        
        factory = ModbusClientFactory(config)
        
        mock_tcp_client = AsyncMock()
        mock_tcp_client.connected = False  # Primera conexión falla
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client) as mock_class:
            clients = await factory.start_connection()
        
        # Solo debe intentar conectar 1 vez (no 2)
        assert mock_class.call_count == 1
        assert len(clients) == 0
        assert "192.168.1.100" in factory.failed_clients
    
    @pytest.mark.asyncio
    async def test_close_all_connections(self):
        """✅ Cerrar todas las conexiones activas"""
        config = {
            "device_1": {
                NameParamsModbus.protocol: ProtocolCom.TCP,
                NameParamsModbus.host: "192.168.1.100",
                NameParamsModbus.port: 502,
                NameParamsModbus.device_id: 1,
            }
        }
        
        factory = ModbusClientFactory(config)
        
        mock_tcp_client = AsyncMock()
        mock_tcp_client.connected = True
        
        with patch('src.Modbus.client.AsyncModbusTcpClient', return_value=mock_tcp_client):
            await factory.start_connection()
        
        # Verificar que hay clientes
        assert len(factory.clients) == 1
        
        # Cerrar todos
        await factory.close_all_connections()
        
        # Verificar que se cerró el cliente
        mock_tcp_client.close.assert_called_once()
        
        # Verificar que se limpió el diccionario
        assert len(factory.clients) == 0
    
    def test_get_connected_clients_count(self):
        """✅ Contador de clientes conectados"""
        factory = ModbusClientFactory({})
        
        # Agregar clientes manualmente
        factory.clients = {
            "192.168.1.100": {},
            "192.168.1.101": {}
        }
        
        assert factory.get_connected_clients_count() == 2
    
    def test_get_failed_clients_count(self):
        """✅ Contador de clientes fallidos"""
        factory = ModbusClientFactory({})
        
        factory.failed_clients = {"192.168.1.100", "192.168.1.101", "192.168.1.102"}
        
        assert factory.get_failed_clients_count() == 3
    
    def test_get_devices_by_client(self):
        """✅ Obtener dispositivos de un cliente específico"""
        factory = ModbusClientFactory({})
        
        factory.clients = {
            "192.168.1.100": {
                NameParamsModbus.devices: [
                    {"device_id": 1, "name": "device_1"},
                    {"device_id": 2, "name": "device_2"}
                ]
            }
        }
        
        devices = factory.get_devices_by_client("192.168.1.100")
        assert len(devices) == 2
        assert devices[0]["device_id"] == 1
    
    def test_get_devices_by_client_not_found(self):
        """✅ Obtener dispositivos de cliente inexistente retorna lista vacía"""
        factory = ModbusClientFactory({})
        
        devices = factory.get_devices_by_client("192.168.1.999")
        assert devices == []
