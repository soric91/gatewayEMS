"""
Tests unitarios para verificar la integración del modelo EnergyPoint.
Verifica que la conversión de datos reales funcione correctamente.
"""

import pytest
from influxdb_client import Point
from src.Models.model import DeviceReadResult, EnergyPoint


class TestEnergyPointIntegration:
    """Tests de integración para EnergyPoint con datos reales."""
    
    def test_from_device_read_result_with_real_data(self, sample_device_read_result):
        """Test: Crear EnergyPoint desde DeviceReadResult con datos reales."""
        energy_point = EnergyPoint.from_device_read_result(sample_device_read_result)
        
        # Verificar conversión correcta
        assert energy_point.device_name == 'Modbus_DTSU666_11'
        assert energy_point.device_id == '11'  # Convertido de int a str
        assert energy_point.device_type == 'CT_Meter'
        assert energy_point.identify_device == 'bf6a469f-4c2a-4402-9438-49a491ad2238'
        assert energy_point.timestamp == '2026-03-29T23:06:29.664999Z'
        assert energy_point.success is True
        assert energy_point.error is None
        
        # Verificar datos reales
        assert len(energy_point.measurements) == 9
        assert energy_point.measurements['VOLTAGE_A'] == 119.9
        assert energy_point.measurements['VOLTAGE_B'] == 120.9
        assert energy_point.measurements['CURRENT_A'] == 3.58
        assert energy_point.measurements['CURRENT_B'] == 0.7
        assert energy_point.measurements['POWER_ACTIVE_INST_TOTAL'] == 465.6
        assert energy_point.measurements['POWER_ACTIVE_INST_A'] == 388.9
        assert energy_point.measurements['POWER_ACTIVE_INST_B'] == 76.7
        assert energy_point.measurements['POWER_ACTIVE_TOTAL_POS'] == 2273.91
        assert energy_point.measurements['POWER_ACTIVE_TOTAL_NEG'] == 874.75
    
    def test_batch_from_results_multiple_devices(self, sample_multiple_device_results):
        """Test: Conversión batch de múltiples resultados (varios device_ids)."""
        energy_points = EnergyPoint.batch_from_results(sample_multiple_device_results)
        
        assert len(energy_points) == 3
        assert all(isinstance(p, EnergyPoint) for p in energy_points)
        
        # Verificar device_ids
        assert energy_points[0].device_id == '11'
        assert energy_points[1].device_id == '12'
        assert energy_points[2].device_id == '13'
        
        # Verificar nombres únicos
        assert energy_points[0].device_name == 'Modbus_DTSU666_11'
        assert energy_points[1].device_name == 'Modbus_DTSU666_12'
        assert energy_points[2].device_name == 'Modbus_DTSU666_13'
    
    def test_to_influx_point_returns_point_object(self, sample_energy_point):
        """Test: Conversión a InfluxDB Point retorna objeto Point."""
        influx_point = sample_energy_point.to_influx_point()
        
        # Verificar que es un objeto Point de InfluxDB
        assert isinstance(influx_point, Point)
        
        # El objeto Point no expone directamente sus campos,
        # pero no debe lanzar error al crearse
    
    def test_normalize_fields_with_real_data(self, sample_energy_point):
        """Test: Normalización de fields con datos reales."""
        # Los datos reales ya vienen como float
        normalized = sample_energy_point._normalize_fields(sample_energy_point.measurements)
        
        # Verificar que todos los valores numéricos son float
        assert all(isinstance(v, float) for v in normalized.values())
        
        # Verificar valores específicos
        assert normalized['VOLTAGE_A'] == 119.9
        assert normalized['CURRENT_A'] == 3.58
        assert normalized['POWER_ACTIVE_INST_TOTAL'] == 465.6
    
    def test_normalize_fields_with_edge_cases(self):
        """Test: Normalización maneja casos especiales."""
        energy_point = EnergyPoint(
            device_name='Test',
            device_id='1',
            device_type='Test',
            identify_device='uuid',
            timestamp='2026-03-29T23:06:29Z',
            measurements={}
        )
        
        normalized = energy_point._normalize_fields({
            'int_value': 10,           # int → float
            'float_value': 10.5,       # float preservado
            'bool_value': True,        # bool preservado
            'str_value': 'test',       # str preservado
            'none_value': None,        # None filtrado
            'empty_str': '',           # str vacío filtrado
            'whitespace': '   ',       # whitespace filtrado
        })
        
        assert normalized['int_value'] == 10.0  # Convertido a float
        assert isinstance(normalized['int_value'], float)
        assert normalized['float_value'] == 10.5
        assert normalized['bool_value'] is True
        assert normalized['str_value'] == 'test'
        
        # Verificar que se filtraron
        assert 'none_value' not in normalized
        assert 'empty_str' not in normalized
        assert 'whitespace' not in normalized
    
    def test_device_id_conversion_from_int_to_str(self):
        """Test: device_id se convierte correctamente de int a str."""
        result = DeviceReadResult(
            device_name='Test',
            device_id=42,  # int (como vienen los datos reales)
            identify_device='uuid',
            timestamp='2026-03-29T23:06:29Z',
            device_type='CT_Meter',
            data={'test': 1},
            success=True
        )
        
        energy_point = EnergyPoint.from_device_read_result(result)
        
        assert energy_point.device_id == '42'
        assert isinstance(energy_point.device_id, str)
    
    def test_failed_result_conversion(self, sample_failed_device_result):
        """Test: Conversión de resultado fallido."""
        energy_point = EnergyPoint.from_device_read_result(sample_failed_device_result)
        
        assert energy_point.success is False
        assert energy_point.error == 'Timeout reading device'
        assert len(energy_point.measurements) == 0  # Sin datos
    
    def test_string_representation(self, sample_energy_point):
        """Test: Representación en string del EnergyPoint."""
        str_repr = str(sample_energy_point)
        
        assert 'CT_Meter' in str_repr
        assert 'Modbus_DTSU666_11' in str_repr
        assert '✅ OK' in str_repr
    
    def test_repr_representation(self, sample_energy_point):
        """Test: Representación técnica del EnergyPoint."""
        repr_str = repr(sample_energy_point)
        
        assert 'EnergyPoint' in repr_str
        assert 'Modbus_DTSU666_11' in repr_str
        assert 'CT_Meter' in repr_str
        assert 'measurements_count=9' in repr_str
