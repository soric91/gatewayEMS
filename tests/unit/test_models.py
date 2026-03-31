"""
Tests unitarios para modelos de datos
"""
import pytest
from pydantic import ValidationError
from src.Models.model import (
    DeviceConfig, NameParamsModbus, ProtocolCom, 
    DATATYPE, DeviceReadResult
)

class TestDeviceConfig:
    """Tests para DeviceConfig (Pydantic)"""
    
    def test_valid_rtu_config(self):
        """Debe validar config RTU válida"""
        config = DeviceConfig(
            protocol="RTU",
            serial_port="/dev/ttyUSB0",
            baudrate=9600,
            device_id=1
        )
        assert config.protocol == "RTU"
        assert config.baudrate == 9600
    
    def test_valid_tcp_config(self):
        """Debe validar config TCP válida"""
        config = DeviceConfig(
            protocol="TCP",
            host="192.168.1.100",
            port="502",
            device_id=[1, 2, 3]
        )
        assert config.protocol == "TCP"
        assert isinstance(config.device_id, list)
        assert len(config.device_id) == 3
    
    def test_default_device_id(self):
        """Debe usar device_id=1 por defecto"""
        config = DeviceConfig(protocol="TCP", host="localhost", port="502")
        assert config.device_id == 1
    
    def test_optional_fields(self):
        """Campos opcionales deben ser None por defecto"""
        config = DeviceConfig(protocol="TCP")
        assert config.host is None
        assert config.modbus_function is None

class TestNameParamsModbus:
    """Tests para enum NameParamsModbus"""
    
    def test_enum_values(self):
        """Debe tener todos los valores esperados"""
        assert NameParamsModbus.protocol.value == "protocol"
        assert NameParamsModbus.device_id.value == "device_id"
        assert str(NameParamsModbus.protocol) == "protocol"
    
    def test_enum_str_representation(self):
        """__str__ debe retornar el valor"""
        assert str(NameParamsModbus.host) == "host"

class TestProtocolCom:
    """Tests para enum ProtocolCom"""
    
    def test_protocol_values(self):
        """Debe tener RTU y TCP"""
        assert ProtocolCom.RTU.value == "RTU"
        assert ProtocolCom.TCP.value == "TCP"
        assert str(ProtocolCom.RTU) == "RTU"

class TestDATATYPE:
    """Tests para enum DATATYPE"""
    
    def test_datatype_values(self):
        """Debe tener todos los tipos de datos"""
        assert DATATYPE.FLOAT.value == "f"
        assert DATATYPE.INT16.value == "h"
        assert DATATYPE.UINT16.value == "H"
        assert DATATYPE.INT32.value == "i"
        assert DATATYPE.UINT32.value == "I"

class TestDeviceReadResult:
    """Tests para DeviceReadResult"""
    
    def test_successful_result(self):
        """Debe crear resultado exitoso"""
        result = DeviceReadResult(
            device_name="TEST_DEVICE",
            device_id="1",
            identify_device="uuid-1234",
            timestamp="2024-01-01T12:00:00Z",
            data={"voltage": 220.0, "current": 15.0},
            success=True
        )
        assert result.success is True
        assert result.error is None
        assert len(result.data) == 2
    
    def test_failed_result(self):
        """Debe crear resultado con error"""
        result = DeviceReadResult(
            device_name="TEST_DEVICE",
            device_id="1",
            identify_device="uuid-1234",
            timestamp="2024-01-01T12:00:00Z",
            data={},
            success=False,
            error="Connection timeout"
        )
        assert result.success is False
        assert result.error == "Connection timeout"
        assert len(result.data) == 0
