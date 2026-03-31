"""
Datos Modbus simulados para tests
"""
import struct

def create_float_registers(value: float) -> list:
    """Convierte un float en 2 registros Modbus (big-endian)"""
    packed = struct.pack('>f', value)
    reg1, reg2 = struct.unpack('>HH', packed)
    return [reg1, reg2]

def create_int32_registers(value: int) -> list:
    """Convierte un int32 en 2 registros Modbus"""
    packed = struct.pack('>i', value)
    reg1, reg2 = struct.unpack('>HH', packed)
    return [reg1, reg2]

def create_uint32_registers(value: int) -> list:
    """Convierte un uint32 en 2 registros Modbus"""
    packed = struct.pack('>I', value)
    reg1, reg2 = struct.unpack('>HH', packed)
    return [reg1, reg2]

# Datos de ejemplo
SAMPLE_VOLTAGE = 220.5
SAMPLE_CURRENT = 15.3
SAMPLE_POWER = 3373  # 220.5 * 15.3

MOCK_MODBUS_RESPONSE = (
    create_float_registers(SAMPLE_VOLTAGE) +
    create_float_registers(SAMPLE_CURRENT) +
    create_int32_registers(SAMPLE_POWER)
)
