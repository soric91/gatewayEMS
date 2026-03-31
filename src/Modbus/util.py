import json
from src.Utils.logging import get_logger
from src.Models.model import NameParamsModbus, DATATYPE
from dataclasses import dataclass
from typing import List, Dict, Any
import struct

logger = get_logger(__name__)

def load_json_file(file_path: str, deviceName: str) -> dict:
    """Carga un archivo JSON y devuelve su contenido como un diccionario"""
    try:
        with open(file_path, 'r') as f:
            logger.info(f"Cargando archivo JSON: {file_path} para {deviceName}")
            return json.load(f)
    except Exception as e:
        logger.error(f"Error al cargar el archivo JSON {file_path}: {e}")
        return {}
    
    
def get_register_count(data_type: str) -> int:
    """Retorna la cantidad de registros que ocupa un tipo de dato."""
    if data_type in [DATATYPE.FLOAT, DATATYPE.INT32, DATATYPE.UINT32]:
        return 2
    elif data_type in [DATATYPE.INT16, DATATYPE.UINT16]:
        return 1
    else:
        return 2  
    
def group_addresses_device(map_device: dict, max_gap: int=110, device_name: str="") -> list[dict]:
    """Agrupa direcciones Modbus que están cerca unas de otras para optimizar lecturas"""
    
    try:
        if not map_device:
            return []
        
        items = sorted(
            [(k, int(v[NameParamsModbus.address], 16), v[NameParamsModbus.data_type]) for k, v in map_device.items()],
            key=lambda x: x[1]
        )
        groups = []
        current_group = [items[0]]
        for item in items[1:]:
            _, addr, data_type = item
            _, last_addr, last_data_type = current_group[-1]
            
            last_size = get_register_count(last_data_type)
            gap = addr - (last_addr + last_size)
            if gap <= max_gap:
                current_group.append(item)
            else:
                groups.append(current_group)
                current_group = [item]
        groups.append(current_group)
        
    
        result = []
        for group in groups:
            start_addr = group[0][1] 
            last_addr = group[-1][1]  
            last_data_type = group[-1][2]  
        
            last_size = get_register_count(last_data_type)
            count = (last_addr + last_size) - start_addr
            
            result.append({
                NameParamsModbus.start_address: start_addr,
                NameParamsModbus.count: count
            })
    except Exception as e:
        logger.error(f"Error al agrupar direcciones del dispositivo {device_name}: {e} ")
        return []
    
    return result


@dataclass
class ModbusRegister:
    """Representa un registro Modbus individual con su metadata"""
    name: str
    address: int
    data_type: DATATYPE
    gain: float
    offset: int = 0  
    
    def parse_value(self, raw_registers: List[int]) -> Any:
        """
        Parsea registros crudos al tipo de dato correspondiente.
        
        :param raw_registers: Lista completa de registros leídos del bloque
        :return: Valor parseado según el data_type
        """
        try:
            
            if self.data_type in [DATATYPE.FLOAT, DATATYPE.INT32, DATATYPE.UINT32]:
                
                reg1 = raw_registers[self.offset]
                reg2 = raw_registers[self.offset + 1]
                
               
                bytes_data = struct.pack('>HH', reg1, reg2)
                
                if self.data_type == DATATYPE.FLOAT:
                    value = struct.unpack('>f', bytes_data)[0]
                elif self.data_type == DATATYPE.INT32:
                    value = struct.unpack('>i', bytes_data)[0]
                else:  
                    value = struct.unpack('>I', bytes_data)[0]
                    
            else:  
                reg = raw_registers[self.offset]
                
                if self.data_type == DATATYPE.INT16:
                    
                    value = reg if reg < 32768 else reg - 65536
                else:  
                    value = reg
            
            
            return round((value * self.gain),2)
            
        except (IndexError, struct.error) as e:
            raise ValueError(f"Error parseando {self.name} en offset {self.offset}: {e}")
@dataclass
class ModbusBlockRead:
    """Representa un bloque de lectura Modbus optimizado"""
    start_address: int
    count: int
    registers: List[ModbusRegister]
    
    def parse_all(self, raw_data: List[int]) -> Dict[str, Any]:
        """
        Parsea todos los registros del bloque.
        
        :param raw_data: Lista de registros crudos leídos
        :return: Diccionario {variable_name: parsed_value}
        """
        if len(raw_data) < self.count:
            raise ValueError(
                f"Datos insuficientes: esperados {self.count}, recibidos {len(raw_data)}"
            )
        
        result = {}
        for reg in self.registers:
            try:
                result[reg.name] = reg.parse_value(raw_data)
            except Exception as e:
                result[reg.name] = None
                
                logger.error(f"Error parseando {reg.name}: {e}")
        
        return result


def create_individual_blocks(map_device: dict, device_name: str = "") -> list[dict]:
    """
    Crea un bloque individual para cada variable (sin agrupar).
    Útil para dispositivos que no soportan lectura continua de memoria.
    
    Args:
        map_device: Diccionario con el mapa Modbus del dispositivo
        device_name: Nombre del dispositivo (para logging)
    
    Returns:
        Lista de bloques individuales [{"start_address": addr, "count": size}, ...]
    
    Example:
        >>> map_device = {
        ...     "VOLTAGE_A": {"address": "0x2006", "data_type": "f", "gain": "1"},
        ...     "CURRENT_A": {"address": "0x200C", "data_type": "f", "gain": "1"}
        ... }
        >>> create_individual_blocks(map_device)
        [
            {"start_address": 8198, "count": 2},  # VOLTAGE_A (float = 2 registros)
            {"start_address": 8204, "count": 2}   # CURRENT_A (float = 2 registros)
        ]
    """
    try:
        if not map_device:
            logger.warning(f"Mapa vacío para {device_name}, no se pueden crear bloques individuales")
            return []
        
        result = []
        
        for var_name, var_info in map_device.items():
            # Obtener dirección y tipo de dato
            address = int(var_info[NameParamsModbus.address], 16)
            data_type = var_info[NameParamsModbus.data_type]
            
            # Calcular tamaño del bloque según el tipo de dato
            count = get_register_count(data_type)
            
            # Crear un bloque individual para esta variable
            result.append({
                NameParamsModbus.start_address: address,
                NameParamsModbus.count: count
            })
            
            logger.debug(
                f"Bloque individual para {device_name}.{var_name}: "
                f"address={hex(address)}, count={count}, type={data_type}"
            )
        
        logger.info(
            f"Bloques individuales creados para {device_name}: "
            f"{len(result)} bloques (1 por variable)"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error creando bloques individuales para {device_name}: {e}")
        return []