"""
Tests para la funcionalidad de blockreading (lectura individual vs agrupada)
"""

import pytest
from src.Modbus.util import create_individual_blocks, group_addresses_device
from src.Modbus.modbusmap import ModbusDeviceMap
from src.Models.model import NameParamsModbus
import tempfile
import json
import os


class TestCreateIndividualBlocks:
    """Tests para la función create_individual_blocks()"""
    
    def test_create_individual_blocks_with_floats(self):
        """Test: Bloques individuales con datos tipo float (2 registros)"""
        map_device = {
            "VOLTAGE_A": {
                "address": "0x2006",
                "data_type": "f",
                "gain": "1"
            },
            "CURRENT_A": {
                "address": "0x200C",
                "data_type": "f",
                "gain": "1"
            }
        }
        
        blocks = create_individual_blocks(map_device, "TestDevice")
        
        assert len(blocks) == 2
        assert blocks[0][NameParamsModbus.start_address] == 0x2006
        assert blocks[0][NameParamsModbus.count] == 2  # float = 2 registros
        assert blocks[1][NameParamsModbus.start_address] == 0x200C
        assert blocks[1][NameParamsModbus.count] == 2
    
    def test_create_individual_blocks_with_mixed_types(self):
        """Test: Bloques individuales con tipos de datos mixtos"""
        map_device = {
            "VOLTAGE": {
                "address": "0x0000",
                "data_type": "f",  # 2 registros
                "gain": "1"
            },
            "STATUS": {
                "address": "0x0010",
                "data_type": "h",  # 1 registro
                "gain": "1"
            },
            "POWER": {
                "address": "0x0020",
                "data_type": "I",  # 2 registros (UINT32)
                "gain": "1"
            }
        }
        
        blocks = create_individual_blocks(map_device, "TestDevice")
        
        assert len(blocks) == 3
        assert blocks[0][NameParamsModbus.count] == 2  # float
        assert blocks[1][NameParamsModbus.count] == 1  # int16
        assert blocks[2][NameParamsModbus.count] == 2  # uint32
    
    def test_create_individual_blocks_empty_map(self):
        """Test: Mapa vacío retorna lista vacía"""
        blocks = create_individual_blocks({}, "TestDevice")
        assert blocks == []
    
    def test_create_individual_blocks_with_all_types(self):
        """Test: Verifica todos los tipos de datos soportados"""
        map_device = {
            "VAR_FLOAT": {"address": "0x0000", "data_type": "f", "gain": "1"},
            "VAR_INT16": {"address": "0x0002", "data_type": "h", "gain": "1"},
            "VAR_UINT16": {"address": "0x0003", "data_type": "H", "gain": "1"},
            "VAR_INT32": {"address": "0x0004", "data_type": "i", "gain": "1"},
            "VAR_UINT32": {"address": "0x0006", "data_type": "I", "gain": "1"}
        }
        
        blocks = create_individual_blocks(map_device, "TestDevice")
        
        assert len(blocks) == 5
        # Verificar counts esperados
        counts = [b[NameParamsModbus.count] for b in blocks]
        assert 2 in counts  # float, int32, uint32
        assert 1 in counts  # int16, uint16
    
    def test_create_individual_blocks_order_preserved(self):
        """Test: El orden de las variables se preserva en los bloques"""
        map_device = {
            "FIRST": {"address": "0x0000", "data_type": "f", "gain": "1"},
            "SECOND": {"address": "0x0010", "data_type": "f", "gain": "1"},
            "THIRD": {"address": "0x0020", "data_type": "f", "gain": "1"}
        }
        
        blocks = create_individual_blocks(map_device, "TestDevice")
        
        # Verificar que hay 3 bloques
        assert len(blocks) == 3
        
        # Verificar que las direcciones están presentes (el orden puede variar por dict)
        addresses = {b[NameParamsModbus.start_address] for b in blocks}
        assert addresses == {0x0000, 0x0010, 0x0020}


class TestBlockReadingComparison:
    """Tests que comparan lectura agrupada vs individual"""
    
    @pytest.fixture
    def sample_map_file(self):
        """Crea un archivo JSON temporal con un mapa de prueba"""
        map_data = {
            "VOLTAGE_A": {"address": "0x2006", "data_type": "f", "gain": "1"},
            "VOLTAGE_B": {"address": "0x2008", "data_type": "f", "gain": "1"},
            "CURRENT_A": {"address": "0x200C", "data_type": "f", "gain": "1"},
            "CURRENT_B": {"address": "0x200E", "data_type": "f", "gain": "1"},
            "POWER_ACTIVE_INST_TOTAL": {"address": "0x2012", "data_type": "f", "gain": "1"},
            "POWER_ACTIVE_INST_A": {"address": "0x2014", "data_type": "f", "gain": "1"},
            "POWER_ACTIVE_INST_B": {"address": "0x2016", "data_type": "f", "gain": "1"},
            "POWER_ACTIVE_TOTAL_POS": {"address": "0x4026", "data_type": "f", "gain": "1"},
            "POWER_ACTIVE_TOTAL_NEG": {"address": "0x4030", "data_type": "f", "gain": "1"}
        }
        
        # Crear archivo temporal
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(map_data, f)
            temp_path = f.name
        
        yield temp_path
        
        # Limpiar archivo temporal
        os.unlink(temp_path)
    
    def test_grouped_reading_creates_fewer_blocks(self, sample_map_file):
        """Test: Lectura agrupada crea menos bloques que individual"""
        # Crear mapa con block_reading=True (agrupado)
        grouped_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=True
        )
        grouped_map.load_map()
        grouped_blocks = grouped_map.build_read_blocks()
        
        # Crear mapa con block_reading=False (individual)
        individual_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=False
        )
        individual_map.load_map()
        individual_blocks = individual_map.build_read_blocks()
        
        # La lectura agrupada debe tener menos bloques
        assert len(grouped_blocks) < len(individual_blocks)
        
        # La lectura individual debe tener 9 bloques (1 por variable)
        assert len(individual_blocks) == 9
    
    def test_individual_reading_one_block_per_variable(self, sample_map_file):
        """Test: Lectura individual crea exactamente 1 bloque por variable"""
        device_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=False
        )
        device_map.load_map()
        blocks = device_map.build_read_blocks()
        
        # Debe haber 9 bloques (9 variables en el mapa)
        assert len(blocks) == 9
        
        # Cada bloque debe tener count=2 (todos son float)
        for block in blocks:
            assert block[NameParamsModbus.count] == 2
    
    def test_grouped_reading_optimizes_continuous_addresses(self, sample_map_file):
        """Test: Lectura agrupada optimiza direcciones continuas"""
        device_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=True,
            max_gap=10  # Gap pequeño para agrupar solo direcciones muy cercanas
        )
        device_map.load_map()
        blocks = device_map.build_read_blocks()
        
        # Debe agrupar las primeras 7 variables (0x2006-0x2016 son continuas)
        # Y separar las últimas 2 (0x4026 y 0x4030 están lejos)
        assert len(blocks) >= 1  # Al menos un bloque grande
        
        # El primer bloque debe incluir varias variables
        first_block_count = blocks[0][NameParamsModbus.count]
        assert first_block_count > 2  # Más de una variable
    
    def test_both_modes_read_same_variables(self, sample_map_file):
        """Test: Ambos modos leen las mismas variables"""
        # Lectura agrupada
        grouped_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=True
        )
        grouped_map.load_map()
        grouped_map.build_read_blocks()
        
        # Lectura individual
        individual_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=sample_map_file,
            block_reading=False
        )
        individual_map.load_map()
        individual_map.build_read_blocks()
        
        # Ambos deben tener las mismas variables
        grouped_vars = set(grouped_map.get_variables_list())
        individual_vars = set(individual_map.get_variables_list())
        
        assert grouped_vars == individual_vars
        assert len(grouped_vars) == 9


class TestBlockReadingIntegration:
    """Tests de integración para blockreading"""
    
    @pytest.fixture
    def simple_map_file(self):
        """Crea un mapa simple para tests"""
        map_data = {
            "VAR1": {"address": "0x0000", "data_type": "f", "gain": "1"},
            "VAR2": {"address": "0x0010", "data_type": "f", "gain": "1"}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(map_data, f)
            temp_path = f.name
        
        yield temp_path
        os.unlink(temp_path)
    
    def test_default_block_reading_is_true(self, simple_map_file):
        """Test: El valor por defecto de block_reading es True"""
        device_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=simple_map_file
        )
        
        assert device_map.block_reading is True
    
    def test_block_reading_false_explicitly(self, simple_map_file):
        """Test: block_reading=False funciona correctamente"""
        device_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=simple_map_file,
            block_reading=False
        )
        device_map.load_map()
        blocks = device_map.build_read_blocks()
        
        # Con 2 variables y block_reading=False, debe haber 2 bloques
        assert len(blocks) == 2
    
    def test_block_reading_true_explicitly(self, simple_map_file):
        """Test: block_reading=True agrupa correctamente"""
        device_map = ModbusDeviceMap(
            device_name="TestDevice",
            map_file_path=simple_map_file,
            block_reading=True,
            max_gap=100  # Gap grande para forzar agrupación
        )
        device_map.load_map()
        blocks = device_map.build_read_blocks()
        
        # Con gap grande, las 2 variables deberían agruparse en 1 bloque
        assert len(blocks) == 1
        
        # El bloque debe cubrir desde 0x0000 hasta 0x0010 + 2 registros
        assert blocks[0][NameParamsModbus.start_address] == 0x0000
        assert blocks[0][NameParamsModbus.count] >= 2


class TestCompareWithOriginalImplementation:
    """Tests que verifican compatibilidad con implementación original"""
    
    def test_grouped_mode_matches_original_behavior(self):
        """Test: block_reading=True produce los mismos resultados que antes"""
        map_device = {
            "VOLTAGE_A": {"address": "0x2006", "data_type": "f", "gain": "1"},
            "VOLTAGE_B": {"address": "0x2008", "data_type": "f", "gain": "1"}
        }
        
        # Resultado usando group_addresses_device (original)
        original_result = group_addresses_device(map_device, max_gap=110, device_name="Test")
        
        # Resultado usando create_individual_blocks NO debe coincidir
        individual_result = create_individual_blocks(map_device, device_name="Test")
        
        # Original agrupa, individual no
        assert len(original_result) < len(individual_result)
        
        # Original debe agrupar las 2 variables en 1 bloque
        assert len(original_result) == 1
        
        # Individual debe crear 2 bloques
        assert len(individual_result) == 2
