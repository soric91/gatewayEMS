from time import time
from dataclasses import dataclass
from typing import Dict, Any
from pydantic import BaseModel, Field
from typing import Optional, Union, List
from enum import Enum
from influxdb_client import Point



class DeviceConfig(BaseModel):
    protocol: str
    host: Optional[str] = None
    port: Optional[str] = None
    serial_port: Optional[str] = None
    baudrate: Optional[int] = None
    modbus_function: Optional[int] = None
    device_id: Union[int, List[int]] = Field(default=1)
    modbus_map_path: Optional[str] = None
    
    
    
    
class NameParamsModbus(str,Enum):
    protocol = "protocol"
    host = "host"
    port = "port"
    serial_port = "serial_port"
    baudrate = "baudrate"
    modbus_function = "modbus_function"
    device_id = "device_id"   
    modbus_map_path = "modbus_map_path"
    client = "client"
    address = "address"
    data_type = "data_type"
    gain = "gain"
    start_address = "start_address"
    count = "count"
    devices = "devices"
    device_name = "device_name"
    identify_device = "identify_device"
    device_type = "device_type"
    results = "results"
    success_count = "success_count"
    total_count = "total_count"
    

    def __str__(self) -> str:
        return self.value
    
    
    
class ProtocolCom(str,Enum):
    RTU = "RTU"
    TCP = "TCP"
    
    def __str__(self) -> str:
        return self.value
    
    
class DATATYPE(str,Enum):
    FLOAT = "f"
    INT16 = "h"
    UINT16 = "H"
    INT32 = "i"
    UINT32 = "I"
    
    def __str__(self) -> str:
        return self.value
    
    
@dataclass
class DeviceReadResult:
    """Resultado de lectura con timestamp"""
    device_name: str
    device_id: str
    identify_device: str
    timestamp: str
    data: Dict[str, Any]
    success: bool
    device_type: Optional[str] = "Unknown"
    error: str = None
    
    
    
@dataclass
class EnergyPoint:
    """
    Modelo escalable para puntos de energía desde Modbus.
    
    Soporta:
    - Variables dinámicas (cualquier cantidad/nombre)
    - Múltiples tipos de dispositivos
    - Conversión automática a InfluxDB Point
    
    Ejemplo de uso:
        >>> point = EnergyPoint(
        ...     device_name="Modbus_DTSU666_11",
        ...     device_id="11",
        ...     device_type="CT_Meter",
        ...     identify_device="bf6a469f-...",
        ...     timestamp="2026-03-29T17:59:38.297176Z",
        ...     measurements={"VOLTAGE_A": 118.0, "CURRENT_A": 15.11}
        ... )
        >>> influx_data = point.to_influx_point()
    """
    
    # === TAGS (Indexados en InfluxDB) ===
    device_name: str              # ej: "Modbus_DTSU666_11"
    device_id: str                # ej: "11"
    device_type: str              # ej: "CT_Meter", "Inverter", "Battery"
    identify_device: str          # UUID: "bf6a469f-4c2a-4402-9438-49a491ad2238"
    
    # === TIMESTAMP ===
    timestamp: str                # ISO8601: "2026-03-29T17:59:38.297176Z"
    
    # === FIELDS (Mediciones dinámicas) ===
    measurements: Dict[str, Any]  # Variables Modbus (escalable)
    
    # === METADATA ===
    success: bool = True
    error: Optional[str] = None
    
    # === CONFIGURACIÓN ===
    measurement_name: str = "Modbus_Data"
    
    @classmethod
    def from_device_read_result(cls, result: DeviceReadResult) -> 'EnergyPoint':
        """
        Factory method para crear EnergyPoint desde DeviceReadResult.
        
        Args:
            result: Resultado de lectura Modbus
            
        Returns:
            EnergyPoint creado
        """
        return cls(
            device_name=result.device_name,
            device_id=str(result.device_id),
            device_type=result.device_type,
            identify_device=result.identify_device,
            timestamp=result.timestamp,
            measurements=result.data,
            success=result.success,
            error=result.error
        )
    
    
    @staticmethod
    def batch_from_results(results: List[DeviceReadResult]) -> List['EnergyPoint']:
        """
        Convierte una lista de DeviceReadResult a EnergyPoints.
        
        Args:
            results: Lista de resultados Modbus
            
        Returns:
            Lista de EnergyPoints
        """
        return [
            EnergyPoint.from_device_read_result(result) 
            for result in results
        ]
    
    
    def to_influx_point(self) -> Point:
        """
        Convierte a formato InfluxDB Point.
        
        Returns:
            dict compatible con influxdb_client.Point:
            {
                'measurement': 'Modbus_Data',
                'tags': {...},
                'fields': {...},
                'time': '2026-03-29T17:59:38.297176Z'
            }
        """
        point = (
        Point(self.measurement_name)
        .tag("device_name",     self.device_name)
        .tag("device_id",       self.device_id)
        .tag("device_type",     self.device_type)
        .tag("identify_device", self.identify_device)
        .time(self.timestamp))

        for key, value in self._normalize_fields(self.measurements).items():
            point = point.field(key, value)

        return point
    
    
    def _normalize_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normaliza los fields para InfluxDB.
        
        - Convierte int a float (InfluxDB prefiere floats)
        - Filtra valores None/null
        - Maneja tipos correctamente
        """
        normalized = {}
        
        for key, value in data.items():
            if value is None:
                continue
            elif isinstance(value, bool):
                normalized[key] = value
            elif isinstance(value, (int, float)):
                normalized[key] = float(value)
            elif isinstance(value, str):
                if value.strip():
                    normalized[key] = value
            else:
                normalized[key] = str(value)
        
        return normalized
    
    
    def __str__(self):
        """Representación legible para logs"""
        vars_preview = list(self.measurements.keys())[:3]
        vars_str = ', '.join(vars_preview)
        if len(self.measurements) > 3:
            vars_str += f", ... (+{len(self.measurements) - 3} more)"
        
        return (
            f"📊 {self.device_type} [{self.device_name}]\n"
            f"   Variables: {vars_str}\n"
            f"   Timestamp: {self.timestamp}\n"
            f"   Status: {'✅ OK' if self.success else '❌ Error'}"
        )
    
    
    def __repr__(self):
        """Representación técnica para debugging"""
        return (
            f"EnergyPoint(device_name='{self.device_name}', "
            f"device_type='{self.device_type}', "
            f"measurements_count={len(self.measurements)}, "
            f"success={self.success})"
        )