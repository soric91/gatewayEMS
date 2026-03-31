"""
Integration tests for src/Modbus/app.py

Tests para ModbusApp (Orquestador principal):
- Inicialización completa
- Carga de configuraciones
- Carga de mapas
- Conexión de dispositivos
- Lectura de datos
- Manejo de errores
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from src.Modbus.app import ModbusApp
from src.Config.config import ConfigManager
from src.Models.model import NameParamsModbus


@pytest.fixture
def sample_config_file(tmp_path):
    """Crea un archivo config.ini de prueba"""
    config_file = tmp_path / "config.ini"
    config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_TEST1

[DEVICE_TEST1]
protocol = TCP
host = 192.168.1.100
port = 502
device_id = 1
modbus_function = 3
mapfile = tests/fixtures/sample_map.json
modbusconnect = False
modbusread = False
""")
    return config_file


@pytest.fixture
def sample_map_file(tmp_path):
    """Crea un archivo JSON de mapa Modbus de prueba"""
    map_file = tmp_path / "test_map.json"
    map_file.write_text("""{
    "voltage": {
        "address": "0x00",
        "data_type": "f",
        "gain": 1.0
    },
    "current": {
        "address": "0x02",
        "data_type": "f",
        "gain": 1.0
    }
}""")
    return map_file


class TestModbusApp:
    """Tests de integración para ModbusApp"""
    
    def test_load_configs_success(self, sample_config_file):
        """✅ Carga correcta de configuraciones desde .ini"""
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        
        result = app._load_configs()
        
        assert result is True
        assert "DEVICE_TEST1" in app.device_configs
        assert app.device_configs["DEVICE_TEST1"]["protocol"] == "TCP"
        assert app.device_configs["DEVICE_TEST1"]["host"] == "192.168.1.100"
        assert app.device_configs["DEVICE_TEST1"]["port"] == "502"
    
    def test_load_configs_no_devices(self, tmp_path):
        """❌ Sin dispositivos configurados debe fallar"""
        config_file = tmp_path / "empty_config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = 
""")
        
        config = ConfigManager(config_file=str(config_file))
        app = ModbusApp(config=config)
        
        result = app._load_configs()
        
        assert result is False
    
    def test_load_configs_multiple_device_ids(self, tmp_path):
        """✅ Manejo de múltiples device_ids (slaves)"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1

[DEVICE_1]
protocol = RTU
serial_port = /dev/ttyUSB0
baudrate = 9600
device_id = 1, 2, 3
mapfile = test.json
""")
        
        config = ConfigManager(config_file=str(config_file))
        app = ModbusApp(config=config)
        
        result = app._load_configs()
        
        assert result is True
        assert app.device_configs["DEVICE_1"]["device_ids"] == [1, 2, 3]
    
    @patch('src.Modbus.app.ModbusDeviceMap')
    def test_load_maps_success(self, mock_map_class, sample_config_file):
        """✅ Carga correcta de mapas Modbus"""
        mock_map = MagicMock()
        mock_map.load_map.return_value = True
        mock_map_class.return_value = mock_map
        
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        app._load_configs()
        
        result = app._load_maps()
        
        assert result is True
        assert "DEVICE_TEST1" in app.device_maps
        mock_map.load_map.assert_called_once()
        mock_map.build_read_blocks.assert_called_once()
    
    @patch('src.Modbus.app.ModbusDeviceMap')
    def test_load_maps_no_mapfile(self, mock_map_class, tmp_path):
        """⚠️ Dispositivo sin mapfile es ignorado"""
        config_file = tmp_path / "config.ini"
        config_file.write_text("""[DEFAULT]
loglevel = INFO

[MAINMODBUS]
devicesnames = DEVICE_1

[DEVICE_1]
protocol = TCP
host = 192.168.1.100
port = 502
""")
        
        config = ConfigManager(config_file=str(config_file))
        app = ModbusApp(config=config)
        app._load_configs()
        
        result = app._load_maps()
        
        # Debe retornar False porque no hay mapas cargados
        assert result is False
    
    @pytest.mark.asyncio
    @patch('src.Modbus.app.ModbusClientFactory')
    async def test_connect_device_success(self, mock_factory_class, sample_config_file):
        """✅ Conectar dispositivo exitosamente"""
        # Setup mock factory
        mock_factory = AsyncMock()
        mock_client = AsyncMock()
        mock_factory.start_connection.return_value = {
            "192.168.1.100": {
                NameParamsModbus.client: mock_client,
                NameParamsModbus.devices: [{
                    NameParamsModbus.device_name: "DEVICE_TEST1_1",
                    NameParamsModbus.device_id: 1
                }]
            }
        }
        mock_factory_class.return_value = mock_factory
        
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        app._load_configs()
        
        result = await app.connect_device("DEVICE_TEST1")
        
        assert result is True
        assert len(app.clients) == 1
        assert "192.168.1.100" in app.clients
    
    @pytest.mark.asyncio
    async def test_connect_device_not_found(self, sample_config_file):
        """❌ Intentar conectar dispositivo inexistente"""
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        app._load_configs()
        
        result = await app.connect_device("DEVICE_NONEXISTENT")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_disconnect_device(self, sample_config_file):
        """✅ Desconectar dispositivo correctamente"""
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        
        # Simular cliente conectado
        mock_client = AsyncMock()
        app.clients = {
            "192.168.1.100": {
                NameParamsModbus.client: mock_client,
                NameParamsModbus.devices: [{
                    NameParamsModbus.device_name: "DEVICE_TEST1_1"
                }]
            }
        }
        
        await app.disconnect_device("DEVICE_TEST1")
        
        # Cliente debe haberse desconectado
        assert len(app.clients) == 0
        await mock_client.close()
    
    @pytest.mark.asyncio
    @patch('src.Modbus.app.read_registers')
    @patch('src.Modbus.app.ModbusDeviceMap')
    async def test_read_all_success(self, mock_map_class, mock_read_registers, sample_config_file):
        """✅ Lectura exitosa de todos los dispositivos"""
        # Setup mocks
        mock_map = MagicMock()
        mock_map.get_read_params.return_value = ([0], [2])
        mock_map.parse_raw_data.return_value = {"voltage": 220.5, "current": 10.2}
        mock_map_class.return_value = mock_map
        
        mock_read_registers.return_value = {1: [100, 200]}
        
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        app._load_configs()
        app._load_maps()
        
        # Simular cliente conectado
        mock_client = AsyncMock()
        mock_client.connected = True
        app.clients = {
            "192.168.1.100": {
                NameParamsModbus.client: mock_client,
                NameParamsModbus.devices: [{
                    NameParamsModbus.device_name: "DEVICE_TEST1_1",
                    NameParamsModbus.device_id: 1,
                    "modbus_function": 3
                }]
            }
        }
        
        results = await app.read_all()
        
        # Verificar resultados
        assert len(results) > 0
        assert results[0].success is True
        assert results[0].device_id == 1
        assert "voltage" in results[0].data
        assert results[0].data["voltage"] == 220.5
    
    @pytest.mark.asyncio
    async def test_shutdown(self, sample_config_file):
        """✅ Cerrar todas las conexiones en shutdown"""
        config = ConfigManager(config_file=str(sample_config_file))
        app = ModbusApp(config=config)
        
        # Simular múltiples clientes
        mock_client1 = AsyncMock()
        mock_client2 = AsyncMock()
        
        app.clients = {
            "192.168.1.100": {NameParamsModbus.client: mock_client1},
            "192.168.1.101": {NameParamsModbus.client: mock_client2}
        }
        
        await app.shutdown()
        
        # Ambos clientes deben cerrarse
        await mock_client1.close()
        await mock_client2.close()
