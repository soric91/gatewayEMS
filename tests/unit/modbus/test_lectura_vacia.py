"""
Una lectura que no produce ninguna variable no puede reportarse como buena.

En producción salía esto:

    {"device_name": "Modbus_EMSIMONO_74", "data": {}, "success": true, "error": null}

`parse_raw_data` devuelve `{}` cuando los registros que vuelven no alcanzan
para ningún bloque (mapa mal direccionado, esclavo que no responde con lo
esperado…), y aun así el resultado se marcaba como éxito: el fallo quedaba
invisible y el dato vacío seguía camino a InfluxDB y a MQTT.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.Database.service import ModbusService
from src.Modbus.app import ModbusApp
from src.Models.model import DeviceReadResult, NameParamsModbus

pytestmark = pytest.mark.unit

SECCION = "Modbus_EMSIMONO"


def app_con_un_esclavo(parsed: dict) -> ModbusApp:
    """ModbusApp con un cliente y un mapa cuyo parseo devuelve `parsed`."""
    app = ModbusApp()

    device_map = MagicMock()
    device_map.get_read_params.return_value = ([0xA612], [2])
    device_map.parse_raw_data.return_value = parsed
    device_map.get_variables_list.return_value = ["Voltaje_A"]
    app.device_maps = {SECCION: device_map}

    app.clients = {
        "/dev/ttyRS485": {
            NameParamsModbus.client: MagicMock(),
            NameParamsModbus.devices: [
                {
                    NameParamsModbus.device_name: f"{SECCION}_74",
                    NameParamsModbus.device_section: SECCION,
                    NameParamsModbus.device_id: 74,
                    NameParamsModbus.modbus_function: 3,
                }
            ],
        }
    }
    return app


async def leer(app: ModbusApp, registros=(0, 0)):
    with patch("src.Modbus.app.read_registers", AsyncMock(return_value={74: list(registros)})):
        return await app.read_all()


async def test_lectura_sin_variables_no_es_exito():
    resultados = await leer(app_con_un_esclavo({}))

    assert len(resultados) == 1
    assert resultados[0].data == {}
    assert resultados[0].success is False
    assert resultados[0].error == "lectura sin variables"


async def test_lectura_con_variables_sigue_siendo_exito():
    resultados = await leer(app_con_un_esclavo({"Voltaje_A": 119.9}))

    assert resultados[0].success is True
    assert resultados[0].error is None
    assert resultados[0].data == {"Voltaje_A": 119.9}


# --- lo que llega a InfluxDB ----------------------------------------------


def resultado(data: dict, success: bool = True) -> DeviceReadResult:
    return DeviceReadResult(
        device_name=f"{SECCION}_74",
        device_section=SECCION,
        device_id=74,
        identify_device="7d8704bd-5fe0-4686-972e-a71febc718d7",
        timestamp=datetime.now(timezone.utc),
        data=data,
        success=success,
        device_type="CT_Meter",
    )


@pytest.fixture
def service():
    servicio = ModbusService(_repository=AsyncMock())
    return servicio


async def test_no_se_guardan_lecturas_vacias(service):
    await service.save_batch([resultado({}, success=False)])

    service._repository.save_points.assert_not_awaited()


async def test_una_lectura_vacia_no_arrastra_a_las_buenas(service):
    """Lo que se guarda es la buena; la vacía se descarta, no el lote."""
    await service.save_batch([
        resultado({"Voltaje_A": 119.9}),
        resultado({}, success=False),
    ])

    puntos = service._repository.save_points.await_args.args[0]
    assert len(puntos) == 1
    assert "Voltaje_A=119.9" in puntos[0].to_line_protocol()


async def test_un_punto_sin_fields_no_produce_linea(service):
    """La razón de descartarlas: el Point resultante se serializa a nada."""
    from src.Models.model import EnergyPoint

    punto = EnergyPoint.from_device_read_result(resultado({})).to_influx_point()

    assert punto.to_line_protocol() == ""
