"""
Fixtures globales compartidas por todos los tests
"""
import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from src.Config.config import ConfigManager

# Import InfluxDB fixtures
pytest_plugins = ['tests.fixtures.influxdb_fixtures']

@pytest.fixture(scope="session")
def event_loop():
    """Event loop para tests asyncio"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def temp_dir():
    """Directorio temporal para tests"""
    temp = tempfile.mkdtemp()
    yield Path(temp)
    shutil.rmtree(temp)

@pytest.fixture
def sample_config_ini(temp_dir):
    """Crea un config.ini de prueba"""
    config_content = """[DEFAULT]
loglevel = INFO
logstdout = False
logfile = test.log
max_size_bytes = 1485760
backup_count = 2

[MAINMODBUS]
devicesnames = TEST_DEVICE_1, TEST_DEVICE_2
interval = 1
start_hour = 0
stop_hour = 23

[TEST_DEVICE_1]
identify_device = test-uuid-1
protocol = RTU
serialport = /dev/ttyUSB0
baudrate = 9600
mapfile = test_map.json
device_id = 1
modbusconnect = false
modbusread = false

[TEST_DEVICE_2]
identify_device = test-uuid-2
protocol = TCP
host = 192.168.1.100
port = 502
mapfile = test_map2.json
device_id = 1,2,3
modbusconnect = false
modbusread = false
"""
    config_file = temp_dir / "config.ini"
    config_file.write_text(config_content)
    return config_file

@pytest.fixture
def sample_modbus_map(temp_dir):
    """Crea un mapa Modbus JSON de prueba"""
    map_content = """{
    "VOLTAGE_A": {
        "address": "0x2000",
        "data_type": "f",
        "gain": "1"
    },
    "CURRENT_A": {
        "address": "0x2002",
        "data_type": "f",
        "gain": "0.1"
    },
    "POWER": {
        "address": "0x2004",
        "data_type": "i",
        "gain": "1"
    }
}"""
    map_file = temp_dir / "test_map.json"
    map_file.write_text(map_content)
    return map_file

@pytest.fixture
def mock_modbus_client():
    """Mock de cliente Modbus"""
    from unittest.mock import AsyncMock, MagicMock
    client = AsyncMock()
    client.connected = True
    client.connect = AsyncMock(return_value=True)
    client.close = AsyncMock()
    return client

@pytest.fixture
def sample_registers():
    """Registros Modbus de ejemplo para el mapa de prueba"""
    import struct
    # Crear datos para el mapa: VOLTAGE_A (0x2000), CURRENT_A (0x2002), POWER (0x2004)
    # Todo en un bloque continuo de 6 registros (0x2000-0x2005)
    voltage_regs = list(struct.unpack('>HH', struct.pack('>f', 220.0)))
    current_regs = list(struct.unpack('>HH', struct.pack('>f', 25.0)))
    power_regs = list(struct.unpack('>HH', struct.pack('>i', 1000)))
    return voltage_regs + current_regs + power_regs


@pytest.fixture
def influxdb_config():
    """InfluxDB configuration for testing"""
    from dataclasses import dataclass
    
    @dataclass
    class InfluxDBConfig:
        url: str
        token: str
        org: str
        bucket: str
    
    return InfluxDBConfig(
        url="http://localhost:8086",
        token="test-token-1234567890",
        org="test-org",
        bucket="test-bucket"
    )


@pytest.fixture
def sample_device_results():
    """Fixture with mixed successful and failed results"""
    from src.Models.model import DeviceReadResult
    return [
        DeviceReadResult(
            device_name='Modbus_DTSU666_11',
            device_id=11,
            identify_device='bf6a469f-4c2a-4402-9438-49a491ad2238',
            timestamp='2026-03-29T23:06:29.664999Z',
            data={
                'VOLTAGE_A': 119.9,
                'CURRENT_A': 3.58,
                'POWER_ACTIVE_INST_TOTAL': 465.6,
            },
            success=True,
            device_type='CT_Meter',
            error=None
        ),
        DeviceReadResult(
            device_name='Modbus_DTSU666_12',
            device_id=12,
            identify_device='abc123-4567-890a-bcde-fghijklmnop',
            timestamp='2026-03-29T23:06:29.664999Z',
            data={
                'VOLTAGE_A': 121.5,
                'CURRENT_A': 4.2,
                'POWER_ACTIVE_INST_TOTAL': 510.3,
            },
            success=True,
            device_type='CT_Meter',
            error=None
        ),
        DeviceReadResult(
            device_name='Modbus_DTSU666_99',
            device_id=99,
            identify_device='failed-device-uuid',
            timestamp='2026-03-29T23:06:29.664999Z',
            data={},
            success=False,
            device_type='CT_Meter',
            error='Timeout reading device'
        ),
    ]


@pytest.fixture
def failed_device_result():
    """Fixture of a failed result"""
    from src.Models.model import DeviceReadResult
    return DeviceReadResult(
        device_name='Modbus_DTSU666_99',
        device_id=99,
        identify_device='failed-device-uuid',
        timestamp='2026-03-29T23:06:29.664999Z',
        data={},
        success=False,
        device_type='CT_Meter',
        error='Timeout reading device'
    )
