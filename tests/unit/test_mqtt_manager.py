"""
Tests de `MQTTManager.publish`.

BUG CORREGIDO: el `await self._client.publish(...)` estaba indentado DENTRO de
`if not isinstance(payload, str):`, así que un payload ya serializado no se
publicaba nunca y no producía ningún error visible. La rama de reconexión, a su
vez, usaba `self.settings.qos`, atributo inexistente (AttributeError).
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import aiomqtt
import pytest

from src.Core.config import settings
from src.Models.model import DeviceReadResult
from src.Utils.utils import MQTTManager

pytestmark = pytest.mark.unit


@pytest.fixture
def manager():
    mgr = MQTTManager()
    mgr._client = AsyncMock()
    return mgr


TOPIC = "gateway/modbus/data"


def payload_publicado(client_mock, llamada: int = 0):
    """Devuelve (topic, mensaje, qos) de la llamada indicada a publish()."""
    args, kwargs = client_mock.publish.await_args_list[llamada]
    return args[0], args[1], kwargs["qos"]


async def test_publica_dict_como_json(manager):
    await manager.publish(TOPIC, {"device_name": "Modbus_DTSU666_11", "VOLTAGE_A": 118.0})

    topic, mensaje, qos = payload_publicado(manager._client)
    assert topic == TOPIC
    assert qos == settings.MQTT_QOS
    assert json.loads(mensaje) == {
        "device_name": "Modbus_DTSU666_11",
        "VOLTAGE_A": 118.0,
    }


async def test_regresion_publica_payload_que_ya_es_str(manager):
    """Antes: payload str entraba en el `else` del isinstance y NO se publicaba."""
    await manager.publish(TOPIC, "ya-serializado")

    manager._client.publish.assert_awaited_once()
    _, mensaje, _ = payload_publicado(manager._client)
    assert mensaje == "ya-serializado"


async def test_publica_dataclass_DeviceReadResult(manager):
    resultado = DeviceReadResult(
        device_name="Modbus_DTSU666_11",
        device_id=11,
        identify_device="bf6a469f-4c2a-4402-9438-49a491ad2238",
        timestamp=datetime.now(timezone.utc),
        data={"VOLTAGE_A": 118.0, "CURRENT_A": 15.11},
        success=True,
        device_type="CT_Meter",
    )

    await manager.publish(TOPIC, resultado)

    _, mensaje, _ = payload_publicado(manager._client)
    decodificado = json.loads(mensaje)
    assert decodificado["device_name"] == "Modbus_DTSU666_11"
    assert decodificado["data"]["VOLTAGE_A"] == 118.0
    assert decodificado["success"] is True


async def test_sin_cliente_no_lanza_y_no_publica():
    mgr = MQTTManager()  # _client is None

    await mgr.publish(TOPIC, {"n": 1})  # no debe lanzar

    assert mgr._client is None


async def test_reconecta_y_reintenta_si_se_pierde_la_conexion(monkeypatch):
    mgr = MQTTManager()
    cliente_caido = AsyncMock()
    cliente_caido.publish.side_effect = aiomqtt.MqttError("conexión perdida")
    mgr._client = cliente_caido

    cliente_nuevo = AsyncMock()
    reconexiones = []

    async def fake_connect():
        reconexiones.append(True)
        mgr._client = cliente_nuevo

    async def fake_disconnect():
        mgr._client = None

    monkeypatch.setattr(mgr, "connect", fake_connect)
    monkeypatch.setattr(mgr, "disconnect", fake_disconnect)

    await mgr.publish(TOPIC, {"n": 1})

    assert reconexiones == [True]
    cliente_nuevo.publish.assert_awaited_once()
    topic, mensaje, qos = payload_publicado(cliente_nuevo)
    assert topic == TOPIC
    assert qos == settings.MQTT_QOS          # antes: self.settings.qos -> AttributeError
    assert json.loads(mensaje) == {"n": 1}


async def test_serializa_valores_no_json_sin_romper(manager):
    """`default=str` cubre tipos exóticos (datetime, Decimal, ...)."""
    momento = datetime(2026, 3, 29, 17, 59, 38, tzinfo=timezone.utc)

    await manager.publish(TOPIC, {"timestamp": momento})

    _, mensaje, _ = payload_publicado(manager._client)
    assert "2026-03-29" in json.loads(mensaje)["timestamp"]
