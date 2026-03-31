
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
import asyncio
from typing import Dict, List, Optional, Union
from src.Utils.logging import get_logger

logger = get_logger(__name__)

async def read_slave_data(client: Union[AsyncModbusSerialClient, AsyncModbusTcpClient], slave: int, address: int, count: int, function_code: int = 3) -> Optional[List[int]]:
    """
    Lee registros de un solo esclavo en una dirección específica.
    """
    try:
        if not client.connected:
            logger.warning(f"Cliente Modbus no conectado para el esclavo {slave}.")
            return None

        if function_code not in [3, 4]:
            raise ValueError("Código de función inválido. Debe ser 3 (read holding) o 4 (read input).")

        response = await client.read_holding_registers(address = address, count = count, device_id =slave) if function_code == 3 \
            else await client.read_input_registers(address = address,count= count, device_id =slave)

        if response.isError():
            logger.error(f"❌ Error al leer registros del esclavo {slave}, address {address}, count {count}: {response}")
            return None

        return response.registers

    except Exception as e:

        logger.error(f"⚠️ Error inesperado al leer registros del esclavo {slave}: {e}")
        return None


async def read_registers(
    client: Union[AsyncModbusSerialClient, AsyncModbusTcpClient], 
    slave: Union[int, List[int]], 
    address: Union[int, List[int]], 
    count: Union[int, List[int]],
    function_code: int = 3
) -> Dict[int, List[int]]:
    """
    Reads Modbus registers and returns a dictionary structured by `slave_id`.
    """
    resultados = {}

    if not client.connected:
        await client.connect()
    
    if not client.connected:
        logger.error("Cliente Modbus no conectado después del intento de reconexión.")
        raise ConnectionError("Cliente Modbus no conectado.")

    if isinstance(slave, int):
        slave = [slave]
    if isinstance(address, int):
        address = [address] * len(slave)
    if isinstance(count, int):
        count = [count] * len(slave)

    if not (isinstance(address, list) and isinstance(count, list) and len(address) == len(count)):
        logger.error("`address` y `count` deben ser listas del mismo tamaño.")
        raise ValueError("`address` y `count` deben ser listas del mismo tamaño.")

    tasks = {s: asyncio.gather(*(read_slave_data(client=client, slave =s,address= a,count= c, function_code=function_code) for a, c in zip(address, count))) for s in slave}

    responses = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for s, res_list in zip(tasks.keys(), responses):
        if isinstance(res_list, Exception):
            logger.error(f"Error en lectura del esclavo {s}: {res_list}")
            continue
        resultados[s] = [item for sublist in res_list if sublist for item in sublist]
        logger.info(f"Lectura consolidada del esclavo {s}: {len(resultados[s])} registros leídos.")
    
    return resultados