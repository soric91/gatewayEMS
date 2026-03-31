"""
Tests unitarios para utilidades Modbus
"""
import pytest
import struct
from src.Modbus.util import (
    load_json_file, get_register_count, group_addresses_device,
    ModbusRegister, ModbusBlockRead
)
from src.Models.model import DATATYPE, NameParamsModbus

class TestLoadJsonFile:
    """Tests para load_json_file"""
    
    def test_load_valid_json(self, sample_modbus_map):
        """Debe cargar JSON válido"""
        data = load_json_file(str(sample_modbus_map), "TEST_DEVICE")
        assert isinstance(data, dict)
        assert "VOLTAGE_A" in data
    
    def test_load_nonexistent_file(self):
        """Debe retornar dict vacío si archivo no existe"""
        data = load_json_file("/nonexistent/file.json", "TEST")
        assert data == {}
    
    def test_load_invalid_json(self, temp_dir):
        """Debe retornar dict vacío si JSON es inválido"""
        invalid_file = temp_dir / "invalid.json"
        invalid_file.write_text("{ invalid json }")
        data = load_json_file(str(invalid_file), "TEST")
        assert data == {}

class TestGetRegisterCount:
    """Tests para get_register_count"""
    
    def test_float_uses_2_registers(self):
        """FLOAT debe usar 2 registros"""
        assert get_register_count(DATATYPE.FLOAT) == 2
    
    def test_int32_uses_2_registers(self):
        """INT32 debe usar 2 registros"""
        assert get_register_count(DATATYPE.INT32) == 2
    
    def test_uint32_uses_2_registers(self):
        """UINT32 debe usar 2 registros"""
        assert get_register_count(DATATYPE.UINT32) == 2
    
    def test_int16_uses_1_register(self):
        """INT16 debe usar 1 registro"""
        assert get_register_count(DATATYPE.INT16) == 1
    
    def test_uint16_uses_1_register(self):
        """UINT16 debe usar 1 registro"""
        assert get_register_count(DATATYPE.UINT16) == 1
    
    def test_unknown_type_defaults_to_2(self):
        """Tipo desconocido debe usar 2 registros por defecto"""
        assert get_register_count("unknown") == 2

class TestGroupAddressesDevice:
    """Tests para group_addresses_device"""
    
    def test_group_consecutive_addresses(self):
        """Debe agrupar direcciones consecutivas"""
        map_device = {
            "VAR1": {"address": "0x2000", "data_type": "H"},
            "VAR2": {"address": "0x2001", "data_type": "H"},
            "VAR3": {"address": "0x2002", "data_type": "H"}
        }
        result = group_addresses_device(map_device, max_gap=5)
        assert len(result) == 1
        assert result[0][NameParamsModbus.start_address] == 0x2000
        assert result[0][NameParamsModbus.count] == 3
    
    def test_separate_distant_addresses(self):
        """Debe separar direcciones lejanas"""
        map_device = {
            "VAR1": {"address": "0x2000", "data_type": "H"},
            "VAR2": {"address": "0x3000", "data_type": "H"}  # Muy lejos
        }
        result = group_addresses_device(map_device, max_gap=5)
        assert len(result) == 2
    
    def test_handle_float_sizes(self):
        """Debe considerar tamaño de floats (2 registros)"""
        map_device = {
            "FLOAT1": {"address": "0x2000", "data_type": "f"},
            "FLOAT2": {"address": "0x2002", "data_type": "f"}
        }
        result = group_addresses_device(map_device, max_gap=5)
        assert len(result) == 1
        assert result[0][NameParamsModbus.count] == 4  # 2+2
    
    def test_empty_map(self):
        """Debe manejar mapa vacío"""
        result = group_addresses_device({}, max_gap=5)
        assert result == []

class TestModbusRegister:
    """Tests para ModbusRegister"""
    
    def test_parse_float_value(self):
        """Debe parsear valor float correctamente"""
        reg = ModbusRegister(
            name="VOLTAGE",
            address=0x2000,
            data_type=DATATYPE.FLOAT,
            gain=1.0,
            offset=0
        )
        # Crear registros para 220.5
        raw = list(struct.unpack('>HH', struct.pack('>f', 220.5)))
        value = reg.parse_value(raw)
        assert abs(value - 220.5) < 0.01
    
    def test_parse_int16_value(self):
        """Debe parsear INT16 correctamente"""
        reg = ModbusRegister(
            name="TEMP",
            address=0x2000,
            data_type=DATATYPE.INT16,
            gain=1.0,
            offset=0
        )
        value = reg.parse_value([100])
        assert value == 100
    
    def test_parse_int16_negative(self):
        """Debe parsear INT16 negativo correctamente"""
        reg = ModbusRegister(
            name="TEMP",
            address=0x2000,
            data_type=DATATYPE.INT16,
            gain=1.0,
            offset=0
        )
        value = reg.parse_value([65436])  # -100 en complemento a 2
        assert value == -100
    
    def test_apply_gain(self):
        """Debe aplicar gain correctamente"""
        reg = ModbusRegister(
            name="CURRENT",
            address=0x2000,
            data_type=DATATYPE.INT16,
            gain=0.1,
            offset=0
        )
        value = reg.parse_value([100])
        assert value == 10.0  # 100 * 0.1
    
    def test_parse_with_offset(self):
        """Debe usar offset en lista de registros"""
        reg = ModbusRegister(
            name="VAR",
            address=0x2004,
            data_type=DATATYPE.INT16,
            gain=1.0,
            offset=2  # Tercer registro
        )
        raw = [10, 20, 30, 40]
        value = reg.parse_value(raw)
        assert value == 30
    
    def test_parse_error_insufficient_data(self):
        """Debe lanzar error si faltan datos"""
        reg = ModbusRegister(
            name="FLOAT",
            address=0x2000,
            data_type=DATATYPE.FLOAT,
            gain=1.0,
            offset=0
        )
        with pytest.raises(ValueError):
            reg.parse_value([100])  # Falta un registro

class TestModbusBlockRead:
    """Tests para ModbusBlockRead"""
    
    def test_parse_all_registers(self):
        """Debe parsear todos los registros del bloque"""
        registers = [
            ModbusRegister("VAR1", 0x2000, DATATYPE.INT16, 1.0, 0),
            ModbusRegister("VAR2", 0x2001, DATATYPE.INT16, 1.0, 1),
            ModbusRegister("VAR3", 0x2002, DATATYPE.INT16, 1.0, 2)
        ]
        block = ModbusBlockRead(
            start_address=0x2000,
            count=3,
            registers=registers
        )
        raw_data = [100, 200, 300]
        result = block.parse_all(raw_data)
        
        assert result["VAR1"] == 100
        assert result["VAR2"] == 200
        assert result["VAR3"] == 300
    
    def test_parse_all_insufficient_data(self):
        """Debe lanzar error si faltan datos"""
        registers = [
            ModbusRegister("VAR1", 0x2000, DATATYPE.INT16, 1.0, 0)
        ]
        block = ModbusBlockRead(0x2000, 3, registers)
        
        with pytest.raises(ValueError):
            block.parse_all([100])  # Faltan 2 registros
    
    def test_parse_all_with_errors(self):
        """Debe manejar errores individuales sin fallar"""
        registers = [
            ModbusRegister("GOOD", 0x2000, DATATYPE.INT16, 1.0, 0),
            ModbusRegister("BAD", 0x2001, DATATYPE.FLOAT, 1.0, 1),  # Faltará un reg
        ]
        block = ModbusBlockRead(0x2000, 2, registers)
        result = block.parse_all([100, 200])
        
        assert result["GOOD"] == 100
        assert result["BAD"] is None  # Error al parsear
