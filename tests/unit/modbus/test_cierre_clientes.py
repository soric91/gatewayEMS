"""
Cierre de clientes Modbus.

`ModbusBaseClient.close()` es SÍNCRONO en pymodbus 3.x: hacerle `await`
lanzaba `TypeError: object NoneType can't be used in 'await' expression` y la
conexión se quedaba abierta. En la recarga en caliente eso dejaba el puerto
serie ocupado y el watchdog abría un segundo handle sobre el mismo RS485.

Los tests van contra la firma real de pymodbus (`spec=`), no contra un mock
libre: si mañana `close()` pasa a ser corrutina, aquí se ve.
"""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymodbus.client import AsyncModbusSerialClient

from src.Modbus.app import ModbusApp
from src.Modbus.client import ModbusClientFactory, cerrar_cliente
from src.Models.model import NameParamsModbus

pytestmark = pytest.mark.unit

SECCION = "Modbus_EMSIMONO"


def cliente_pymodbus() -> MagicMock:
    """Doble con la firma real: close() síncrono, como en pymodbus 3.12."""
    return MagicMock(spec=AsyncModbusSerialClient)


def entrada(client, seccion: str = SECCION) -> dict:
    return {
        NameParamsModbus.client: client,
        NameParamsModbus.devices: [
            {
                NameParamsModbus.device_name: f"{seccion}_74",
                NameParamsModbus.device_section: seccion,
                NameParamsModbus.device_id: 74,
            }
        ],
    }


# --- el ayudante -----------------------------------------------------------

def test_close_de_pymodbus_no_es_corrutina():
    """La premisa del arreglo, fijada: si cambia, los tests de abajo lo dirán."""
    assert not inspect.iscoroutinefunction(AsyncModbusSerialClient.close)


async def test_cierra_un_cliente_con_close_sincrono():
    client = cliente_pymodbus()

    await cerrar_cliente(client)      # antes: TypeError

    client.close.assert_called_once()


async def test_cierra_un_cliente_con_close_asincrono():
    """Por si pymodbus vuelve a cambiar: se espera lo que sea esperable."""
    client = MagicMock()
    client.close = AsyncMock()

    await cerrar_cliente(client)

    client.close.assert_awaited_once()


# --- desconexión de un dispositivo ----------------------------------------

async def test_disconnect_device_cierra_y_suelta_el_cliente(caplog):
    app = ModbusApp()
    client = cliente_pymodbus()
    app.clients = {"/dev/ttyRS485": entrada(client)}

    with caplog.at_level("ERROR"):
        await app.disconnect_device(SECCION)

    client.close.assert_called_once()
    assert app.clients == {}, "el puerto quedó registrado como conectado"
    # Que se llamara a close() no basta: con el `await` sobre None la llamada
    # también ocurría, y el fallo se quedaba en un log.
    assert caplog.records == [], f"el cierre falló: {[r.message for r in caplog.records]}"


async def test_si_el_cierre_falla_el_cliente_no_se_queda_colgado():
    """Un cliente que no cierra Y sigue en el diccionario es lo peor de los dos mundos."""
    app = ModbusApp()
    client = cliente_pymodbus()
    client.close.side_effect = OSError("puerto ya cerrado")
    app.clients = {"/dev/ttyRS485": entrada(client)}

    await app.disconnect_device(SECCION)

    assert app.clients == {}


async def test_no_toca_los_clientes_de_otras_secciones():
    app = ModbusApp()
    mio, ajeno = cliente_pymodbus(), cliente_pymodbus()
    app.clients = {
        "/dev/ttyRS485": entrada(mio),
        "192.168.1.50": entrada(ajeno, seccion="Otro_Equipo"),
    }

    await app.disconnect_device(SECCION)

    mio.close.assert_called_once()
    ajeno.close.assert_not_called()
    assert list(app.clients) == ["192.168.1.50"]


# --- parada del proceso ----------------------------------------------------

async def test_shutdown_cierra_todos_y_vacia_el_registro(caplog):
    app = ModbusApp()
    uno, dos = cliente_pymodbus(), cliente_pymodbus()
    app.clients = {"/dev/ttyRS485": entrada(uno), "192.168.1.50": entrada(dos)}

    with caplog.at_level("ERROR"):
        await app.shutdown()

    uno.close.assert_called_once()
    dos.close.assert_called_once()
    assert app.clients == {}
    assert caplog.records == [], f"el cierre falló: {[r.message for r in caplog.records]}"


async def test_un_cliente_que_no_cierra_no_impide_cerrar_los_demas():
    app = ModbusApp()
    malo, bueno = cliente_pymodbus(), cliente_pymodbus()
    malo.close.side_effect = OSError("puerto ya cerrado")
    app.clients = {"/dev/ttyRS485": entrada(malo), "192.168.1.50": entrada(bueno)}

    await app.shutdown()

    bueno.close.assert_called_once()


# --- la factoría -----------------------------------------------------------

async def test_close_all_connections_de_la_factoria():
    factory = ModbusClientFactory(config_dict={})
    client = cliente_pymodbus()
    factory.clients = {"/dev/ttyRS485": entrada(client)}

    await factory.close_all_connections()

    client.close.assert_called_once()
    assert factory.clients == {}
