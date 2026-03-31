"""
Datos de configuración de muestra para tests
"""

VALID_DEVICE_CONFIG = {
    "protocol": "RTU",
    "serialport": "/dev/ttyUSB0",
    "baudrate": "9600",
    "device_id": "1",
    "mapfile": "test.json",
    "modbusconnect": "false",
    "modbusread": "false"
}

VALID_TCP_CONFIG = {
    "protocol": "TCP",
    "host": "192.168.1.100",
    "port": "502",
    "device_id": "1,2",
    "mapfile": "test.json",
    "modbusconnect": "false",
    "modbusread": "false"
}

INVALID_CONFIG_MISSING_BAUDRATE = {
    "protocol": "RTU",
    "serialport": "/dev/ttyUSB0",
    # falta baudrate
    "device_id": "1"
}

INVALID_CONFIG_MISSING_PORT = {
    "protocol": "TCP",
    "host": "192.168.1.100",
    # falta port
    "device_id": "1"
}
