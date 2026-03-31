from dataclasses import dataclass
from typing import Dict, List, Any
from src.Models.model import  DATATYPE, NameParamsModbus
from src.Modbus.util import load_json_file, group_addresses_device, create_individual_blocks, ModbusBlockRead, ModbusRegister
from src.Utils.logging import get_logger



logger = get_logger(__name__)


@dataclass
class ModbusDeviceMap:
    """
    Maneja el mapa Modbus de un dispositivo: carga JSON, agrupa direcciones,
    y parsea registros leídos.
    """
    device_name: str
    map_file_path: str
    max_gap: int = 110
    block_reading: bool = True  # True = agrupar bloques, False = lectura individual
    

    _raw_map: Dict[str, Dict[str, str]] = None
    _blocks: List[ModbusBlockRead] = None
    
    def load_map(self) -> bool:
        """
        Carga el archivo JSON del mapa Modbus.
        
        :return: True si se cargó correctamente
        """
        self._raw_map = load_json_file(self.map_file_path, self.device_name)
        
        if not self._raw_map:
            logger.error(f"No se pudo cargar el mapa para {self.device_name}")
            return False
        
        logger.info(f"Mapa cargado: {len(self._raw_map)} variables para {self.device_name}")
        return True
    
    def build_read_blocks(self) -> List[Dict[str, int]]:
        """
        Agrupa direcciones en bloques optimizados de lectura.
        Si block_reading=False, crea un bloque individual por variable.
        
        :return: Lista de bloques [{"start_address": ..., "count": ...}]
        """
        if not self._raw_map:
            logger.error("Debe cargar el mapa primero con load_map()")
            return []
        
        # Lógica condicional: agrupar o individual
        if self.block_reading:
            # MODO ORIGINAL: Agrupar direcciones cercanas
            logger.info(f"Usando lectura agrupada (block_reading=True) para {self.device_name}")
            grouped = group_addresses_device(self._raw_map, self.max_gap, self.device_name)
        else:
            # MODO NUEVO: Lectura individual por variable
            logger.info(f"Usando lectura individual (block_reading=False) para {self.device_name}")
            grouped = create_individual_blocks(self._raw_map, self.device_name)
        
       
        self._blocks = []
        
        for block_info in grouped:
            start_addr = block_info[NameParamsModbus.start_address]
            count = block_info[NameParamsModbus.count]
            
            
            registers_in_block = []
            
            for var_name, var_info in self._raw_map.items():
                var_addr = int(var_info[NameParamsModbus.address], 16)
                
                
                if start_addr <= var_addr < start_addr + count:
                    offset = var_addr - start_addr
                    
                    registers_in_block.append(ModbusRegister(
                        name=var_name,
                        address=var_addr,
                        data_type=DATATYPE(var_info[NameParamsModbus.data_type]),
                        gain=float(var_info.get(NameParamsModbus.gain, 1.0)),
                        offset=offset
                    ))
            
            block = ModbusBlockRead(
                start_address=start_addr,
                count=count,
                registers=registers_in_block
            )
            
            self._blocks.append(block)
        
        # Logging mejorado para mostrar el modo
        mode = "bloques agrupados" if self.block_reading else "bloques individuales"
        logger.info(
            f"Bloques de lectura creados para {self.device_name} ({mode}): "
            f"{len(self._blocks)} bloques, {sum(b.count for b in self._blocks)} registros totales"
        )
        
        return [
            {
                NameParamsModbus.start_address: b.start_address,
                NameParamsModbus.count: b.count
            }
            for b in self._blocks
        ]
    
    def get_read_params(self) -> tuple[List[int], List[int]]:
        """
        Obtiene listas de addresses y counts para read_registers().
        
        :return: (addresses, counts)
        """
        if not self._blocks:
            logger.warning("No hay bloques construidos, llamando build_read_blocks()")
            self.build_read_blocks()
        
        addresses = [b.start_address for b in self._blocks]
        counts = [b.count for b in self._blocks]
        
        return addresses, counts
    
    def parse_raw_data(self, raw_registers: List[int]) -> Dict[str, Any]:
        """
        Parsea registros crudos consolidados a valores por variable.
        
        :param raw_registers: Lista completa de registros leídos (consolidados)
        :return: Diccionario {variable_name: parsed_value}
        """
        if not self._blocks:
            logger.error("No hay bloques definidos para parsear")
            return {}
        
        result = {}
        current_offset = 0
        
        for block in self._blocks:
            
            block_data = raw_registers[current_offset:current_offset + block.count]
            
            if len(block_data) < block.count:
                logger.error(
                    f"Datos insuficientes para bloque {hex(block.start_address)}: "
                    f"esperados {block.count}, recibidos {len(block_data)}"
                )
                current_offset += block.count
                continue
            
            
            parsed = block.parse_all(block_data)
            result.update(parsed)
            
            current_offset += block.count
        
        return result
    
    def get_variables_list(self) -> List[str]:
        """Retorna lista de nombres de variables en el mapa"""
        return list(self._raw_map.keys()) if self._raw_map else []