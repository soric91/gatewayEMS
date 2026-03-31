"""
Fixtures para tests de InfluxDB.
Provee datos de prueba realistas basados en datos reales del sistema.
"""

import pytest
from datetime import datetime, timezone
from typing import List
from src.Models.model import DeviceReadResult, EnergyPoint


@pytest.fixture
def sample_device_read_result() -> DeviceReadResult:
    """
    Fixture que retorna un DeviceReadResult de ejemplo.
    Basado en datos reales del sistema.
    """
    return DeviceReadResult(
        device_name='Modbus_DTSU666_11',
        device_id=11,  # int como en datos reales
        identify_device='bf6a469f-4c2a-4402-9438-49a491ad2238',
        timestamp='2026-03-29T23:06:29.664999Z',
        device_type='CT_Meter',
        data={
            'VOLTAGE_A': 119.9,
            'VOLTAGE_B': 120.9,
            'CURRENT_A': 3.58,
            'CURRENT_B': 0.7,
            'POWER_ACTIVE_INST_TOTAL': 465.6,
            'POWER_ACTIVE_INST_A': 388.9,
            'POWER_ACTIVE_INST_B': 76.7,
            'POWER_ACTIVE_TOTAL_POS': 2273.91,
            'POWER_ACTIVE_TOTAL_NEG': 874.75
        },
        success=True,
        error=None
    )


@pytest.fixture
def sample_multiple_device_results() -> List[DeviceReadResult]:
    """
    Fixture que retorna múltiples DeviceReadResult.
    Simula múltiples device_ids.
    """
    return [
        DeviceReadResult(
            device_name='Modbus_DTSU666_11',
            device_id=11,
            identify_device='bf6a469f-4c2a-4402-9438-49a491ad2238',
            timestamp='2026-03-29T23:06:29.664999Z',
            device_type='CT_Meter',
            data={
                'VOLTAGE_A': 119.9,
                'CURRENT_A': 3.58,
                'POWER_ACTIVE_INST_TOTAL': 465.6,
            },
            success=True,
            error=None
        ),
        DeviceReadResult(
            device_name='Modbus_DTSU666_12',
            device_id=12,
            identify_device='abc123-4567-890a-bcde-fghijklmnop',
            timestamp='2026-03-29T23:06:29.664999Z',
            device_type='CT_Meter',
            data={
                'VOLTAGE_A': 121.5,
                'CURRENT_A': 4.2,
                'POWER_ACTIVE_INST_TOTAL': 510.3,
            },
            success=True,
            error=None
        ),
        DeviceReadResult(
            device_name='Modbus_DTSU666_13',
            device_id=13,
            identify_device='xyz789-0123-456a-bcde-fghijklmnop',
            timestamp='2026-03-29T23:06:29.664999Z',
            device_type='CT_Meter',
            data={
                'VOLTAGE_A': 118.2,
                'CURRENT_A': 2.9,
                'POWER_ACTIVE_INST_TOTAL': 342.8,
            },
            success=True,
            error=None
        ),
    ]


@pytest.fixture
def sample_failed_device_result() -> DeviceReadResult:
    """Fixture de un resultado fallido."""
    return DeviceReadResult(
        device_name='Modbus_DTSU666_99',
        device_id=99,
        identify_device='failed-device-uuid',
        timestamp='2026-03-29T23:06:29.664999Z',
        device_type='CT_Meter',
        data={},
        success=False,
        error='Timeout reading device'
    )


@pytest.fixture
def sample_energy_point(sample_device_read_result) -> EnergyPoint:
    """Fixture que retorna un EnergyPoint."""
    return EnergyPoint.from_device_read_result(sample_device_read_result)


@pytest.fixture
def sample_queue_data(sample_device_read_result) -> dict:
    """
    Fixture que simula datos de la cola.
    Formato exacto usado en task_process_queue().
    """
    return {
        'results': [sample_device_read_result],
        'success_count': 1,
        'total_count': 1
    }


@pytest.fixture
def sample_queue_data_multiple(sample_multiple_device_results) -> dict:
    """Fixture con múltiples dispositivos en cola."""
    return {
        'results': sample_multiple_device_results,
        'success_count': 3,
        'total_count': 3
    }


@pytest.fixture
def sample_mixed_results(sample_multiple_device_results, sample_failed_device_result) -> List[DeviceReadResult]:
    """Fixture con resultados exitosos y fallidos mezclados."""
    return sample_multiple_device_results + [sample_failed_device_result]
