"""
Tests unitarios para ModbusDeviceMap
"""
import pytest
from src.Modbus.modbusmap import ModbusDeviceMap
from src.Models.model import NameParamsModbus

class TestModbusDeviceMap:
    """Tests para ModbusDeviceMap"""
    
    def test_load_map_success(self, sample_modbus_map):
        """Debe cargar mapa correctamente"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        result = device_map.load_map()
        
        assert result is True
        assert device_map._raw_map is not None
        assert "VOLTAGE_A" in device_map._raw_map
    
    def test_load_map_failure(self):
        """Debe fallar al cargar mapa inexistente"""
        device_map = ModbusDeviceMap("TEST", "/nonexistent.json")
        result = device_map.load_map()
        assert result is False
    
    def test_build_read_blocks(self, sample_modbus_map):
        """Debe construir bloques de lectura"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        device_map.load_map()
        blocks = device_map.build_read_blocks()
        
        assert isinstance(blocks, list)
        assert len(blocks) > 0
        assert NameParamsModbus.start_address in blocks[0]
        assert NameParamsModbus.count in blocks[0]
    
    def test_build_blocks_without_load(self):
        """Debe retornar lista vacía si no se cargó el mapa"""
        device_map = ModbusDeviceMap("TEST", "dummy.json")
        blocks = device_map.build_read_blocks()
        assert blocks == []
    
    def test_get_read_params(self, sample_modbus_map):
        """Debe retornar addresses y counts"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        device_map.load_map()
        device_map.build_read_blocks()
        
        addresses, counts = device_map.get_read_params()
        
        assert isinstance(addresses, list)
        assert isinstance(counts, list)
        assert len(addresses) == len(counts)
    
    def test_parse_raw_data(self, sample_modbus_map, sample_registers):
        """Debe parsear datos crudos correctamente"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        device_map.load_map()
        device_map.build_read_blocks()
        
        result = device_map.parse_raw_data(sample_registers)
        
        assert isinstance(result, dict)
        assert "VOLTAGE_A" in result
        assert isinstance(result["VOLTAGE_A"], (int, float))
    
    def test_parse_insufficient_data(self, sample_modbus_map):
        """Debe manejar datos insuficientes"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        device_map.load_map()
        device_map.build_read_blocks()
        
        # Muy pocos registros
        result = device_map.parse_raw_data([1, 2])
        # No debe lanzar excepción, pero puede tener valores None
        assert isinstance(result, dict)
    
    def test_get_variables_list(self, sample_modbus_map):
        """Debe retornar lista de variables"""
        device_map = ModbusDeviceMap("TEST", str(sample_modbus_map))
        device_map.load_map()
        
        variables = device_map.get_variables_list()
        assert isinstance(variables, list)
        assert "VOLTAGE_A" in variables
    
    def test_get_variables_list_empty(self):
        """Debe retornar lista vacía si no hay mapa"""
        device_map = ModbusDeviceMap("TEST", "dummy.json")
        variables = device_map.get_variables_list()
        assert variables == []
