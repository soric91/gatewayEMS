"""
Regresión: la sección de config.ini se lleva como dato, no se deduce del nombre.

`read_all` reconstruía la sección con `device_name.split('_')[0] + '_' + [1]`,
así que sólo funcionaba con nombres de exactamente dos palabras. Con cualquier
otro, `device_maps.get(...)` devolvía None y el dispositivo caía en un
`continue` sin log: conectado, sin leer y sin ningún error visible.

Importa ahora que los nombres los escribe quien da de alta el equipo en el CRM.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.Models.model import NameParamsModbus
from src.Modbus.app import ModbusApp

pytestmark = pytest.mark.unit

NOMBRES = [
    "Medidor",              # una palabra: antes daba "Medidor_11" -> sin mapa
    "Modbus_DTSU666",       # dos palabras: el único caso que funcionaba
    "Modbus_DTSU_666",      # tres palabras: antes daba "Modbus_DTSU" -> sin mapa
    "Inversor_Planta_Sur_2",
]


def _app_con_dispositivo(seccion: str, device_ids=(11,)) -> ModbusApp:
    """ModbusApp con un cliente ya conectado y su mapa cargado."""
    app = ModbusApp(config=MagicMock())
    app.config.get_value.return_value = "valor"

    device_map = MagicMock()
    device_map.get_read_params.return_value = ([0x2000], [4])
    device_map.parse_raw_data.return_value = {"VOLTAGE_A": 220.0}
    app.device_maps = {seccion: device_map}

    app.clients = {
        "/dev/ttyUSB0": {
            NameParamsModbus.client: AsyncMock(connected=True),
            NameParamsModbus.devices: [
                {
                    NameParamsModbus.device_name: f"{seccion}_{device_id}",
                    NameParamsModbus.device_section: seccion,
                    NameParamsModbus.device_id: device_id,
                    NameParamsModbus.modbus_function: 3,
                }
                for device_id in device_ids
            ],
        }
    }
    return app


@pytest.mark.parametrize("seccion", NOMBRES)
async def test_lee_con_cualquier_numero_de_palabras_en_el_nombre(seccion, monkeypatch):
    app = _app_con_dispositivo(seccion)

    async def fake_read_registers(**kwargs):
        return {11: [0, 0, 0, 0]}

    monkeypatch.setattr("src.Modbus.app.read_registers", fake_read_registers)

    resultados = await app.read_all()

    assert len(resultados) == 1, f"'{seccion}' no se leyó"
    assert resultados[0].device_name == f"{seccion}_11"
    assert resultados[0].device_section == seccion
    assert resultados[0].success is True


async def test_los_esclavos_de_una_seccion_se_leen_en_una_sola_llamada(monkeypatch):
    """
    Agrupar por la sección (y no por el nombre con sufijo) es lo que hace que
    los esclavos que comparten mapa entren juntos en `read_registers`.
    """
    app = _app_con_dispositivo("Modbus_DTSU666", device_ids=(11, 12, 13))
    llamadas = []

    async def fake_read_registers(**kwargs):
        llamadas.append(kwargs["slave"])
        return {device_id: [0, 0, 0, 0] for device_id in kwargs["slave"]}

    monkeypatch.setattr("src.Modbus.app.read_registers", fake_read_registers)

    resultados = await app.read_all()

    assert llamadas == [[11, 12, 13]]
    assert len(resultados) == 3
    assert {r.device_section for r in resultados} == {"Modbus_DTSU666"}


async def test_sin_mapa_avisa_en_vez_de_callarse(caplog, monkeypatch):
    """El `continue` mudo era el peor modo de fallo: leer nada sin decir nada."""
    app = _app_con_dispositivo("Medidor")
    app.device_maps = {}  # el mapa no cargó

    monkeypatch.setattr("src.Modbus.app.read_registers", AsyncMock())

    with caplog.at_level("WARNING"):
        resultados = await app.read_all()

    assert resultados == []
    assert any("Sin mapa cargado para 'Medidor'" in r.message for r in caplog.records)


async def test_connect_device_propaga_la_seccion(monkeypatch):
    """La sección viaja desde config.ini hasta el device_info del cliente."""
    app = ModbusApp(config=MagicMock())
    app.device_configs = {
        "Inversor": {
            "protocol": "TCP",
            "host": "192.168.1.50",
            "port": "502",
            "mapfile": "maps/inversor.json",
            "device_ids": [1, 2],
        }
    }

    capturado = {}

    class FakeFactory:
        def __init__(self, config_dict):
            capturado.update(config_dict)

        async def start_connection(self):
            return {"192.168.1.50": {NameParamsModbus.client: AsyncMock(),
                                     NameParamsModbus.devices: []}}

    monkeypatch.setattr("src.Modbus.app.ModbusClientFactory", FakeFactory)

    assert await app.connect_device("Inversor") is True

    assert set(capturado) == {"Inversor_1", "Inversor_2"}
    for entrada in capturado.values():
        assert entrada[NameParamsModbus.device_section] == "Inversor"


async def test_disconnect_device_no_confunde_secciones_con_prefijo_comun(monkeypatch):
    """
    `startswith` desconectaba de más: 'Medidor' habría arrastrado a
    'Medidor_Solar'. La comparación es exacta por sección.
    """
    app = ModbusApp(config=MagicMock())
    cliente_a, cliente_b = AsyncMock(), AsyncMock()
    app.clients = {
        "/dev/ttyUSB0": {
            NameParamsModbus.client: cliente_a,
            NameParamsModbus.devices: [
                {NameParamsModbus.device_name: "Medidor_1",
                 NameParamsModbus.device_section: "Medidor"}
            ],
        },
        "/dev/ttyUSB1": {
            NameParamsModbus.client: cliente_b,
            NameParamsModbus.devices: [
                {NameParamsModbus.device_name: "Medidor_Solar_1",
                 NameParamsModbus.device_section: "Medidor_Solar"}
            ],
        },
    }

    await app.disconnect_device("Medidor")

    assert list(app.clients) == ["/dev/ttyUSB1"]
    cliente_a.close.assert_awaited_once()
    cliente_b.close.assert_not_awaited()
