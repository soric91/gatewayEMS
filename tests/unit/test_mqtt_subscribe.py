"""
Tests de la recepción MQTT: subscribe / on_message / listen / messages.

Cubre lo que hace falta para que el gateway acepte comandos por MQTT:
comodines en los filtros, handlers sync y async, decodificación del payload,
aislamiento de errores de un handler y re-suscripción tras reconectar.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiomqtt
import pytest

from src.Core.config import settings
from src.Utils.utils import MQTTManager

pytestmark = pytest.mark.unit


def mensaje(topic: str, payload: bytes) -> aiomqtt.Message:
    """Mensaje real de aiomqtt: su Topic trae el matching con comodines."""
    return aiomqtt.Message(
        topic=topic, payload=payload, qos=0, retain=False, mid=1, properties=None
    )


def cliente_con_mensajes(mensajes, error_al_final=None):
    """
    Doble del aiomqtt.Client: `messages` es un iterador async que entrega la
    lista dada y luego termina (o lanza `error_al_final`).
    """
    cliente = AsyncMock()

    async def flujo():
        for m in mensajes:
            yield m
        if error_al_final:
            raise error_al_final

    # `messages` es una property en el cliente real
    type(cliente).messages = property(lambda self: flujo())
    return cliente


# --------------------------------------------------------------------------
# subscribe / unsubscribe
# --------------------------------------------------------------------------

async def test_subscribe_usa_el_qos_por_defecto_de_settings():
    mgr = MQTTManager()
    mgr._client = AsyncMock()

    await mgr.subscribe("gateway/cmd")

    mgr._client.subscribe.assert_awaited_once_with("gateway/cmd", qos=settings.MQTT_QOS)


async def test_subscribe_acepta_qos_explicito():
    mgr = MQTTManager()
    mgr._client = AsyncMock()

    await mgr.subscribe("gateway/cmd", qos=2)

    mgr._client.subscribe.assert_awaited_once_with("gateway/cmd", qos=2)


async def test_subscribe_antes_de_conectar_queda_pendiente_y_se_aplica_al_conectar(monkeypatch):
    mgr = MQTTManager()

    await mgr.subscribe("gateway/+/cmd", qos=1)   # sin cliente todavía
    assert mgr._subscriptions == {"gateway/+/cmd": 1}

    cliente = AsyncMock()
    monkeypatch.setattr(
        "src.Utils.utils.aiomqtt.Client", MagicMock(return_value=cliente)
    )

    await mgr.connect()

    cliente.subscribe.assert_awaited_once_with("gateway/+/cmd", qos=1)


async def test_reconectar_restaura_las_suscripciones(monkeypatch):
    """Tras una caída, el gateway debe volver a recibir comandos sin ayuda."""
    mgr = MQTTManager()
    mgr._client = AsyncMock()

    await mgr.subscribe("gateway/cmd", qos=1)
    await mgr.subscribe("gateway/config/#", qos=2)

    cliente_nuevo = AsyncMock()
    monkeypatch.setattr(
        "src.Utils.utils.aiomqtt.Client", MagicMock(return_value=cliente_nuevo)
    )

    await mgr._reconnect()

    suscripciones = {
        c.args[0]: c.kwargs["qos"] for c in cliente_nuevo.subscribe.await_args_list
    }
    assert suscripciones == {"gateway/cmd": 1, "gateway/config/#": 2}


async def test_unsubscribe_borra_el_registro():
    mgr = MQTTManager()
    mgr._client = AsyncMock()
    await mgr.subscribe("gateway/cmd")

    await mgr.unsubscribe("gateway/cmd")

    mgr._client.unsubscribe.assert_awaited_once_with("gateway/cmd")
    assert mgr._subscriptions == {}


# --------------------------------------------------------------------------
# Decodificación del payload
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "crudo,esperado",
    [
        (b'{"cmd": "start", "device": "Modbus_DTSU666"}', {"cmd": "start", "device": "Modbus_DTSU666"}),
        (b"[1, 2, 3]", [1, 2, 3]),
        (b"texto plano", "texto plano"),
        (b"", ""),
        (b"\xff\xfe\x00", b"\xff\xfe\x00"),   # no es UTF-8: se entrega crudo
    ],
)
def test_decode_payload(crudo, esperado):
    assert MQTTManager._decode(crudo) == esperado


# --------------------------------------------------------------------------
# Despacho a handlers
# --------------------------------------------------------------------------

async def test_dispatch_entrega_solo_a_los_filtros_que_casan():
    mgr = MQTTManager()
    recibidos = {"cmd": [], "otros": []}

    mgr.on_message("gateway/+/cmd", lambda t, p: recibidos["cmd"].append((t, p)))
    mgr.on_message("gateway/telemetria", lambda t, p: recibidos["otros"].append((t, p)))

    await mgr._dispatch(mensaje("gateway/DTSU666/cmd", b'{"accion": "read"}'))

    assert recibidos["cmd"] == [("gateway/DTSU666/cmd", {"accion": "read"})]
    assert recibidos["otros"] == []


async def test_dispatch_admite_comodin_multinivel():
    mgr = MQTTManager()
    vistos = []
    mgr.on_message("gateway/#", lambda t, p: vistos.append(t))

    await mgr._dispatch(mensaje("gateway/a/b/c", b"1"))

    assert vistos == ["gateway/a/b/c"]


async def test_dispatch_soporta_handlers_async_y_sync():
    mgr = MQTTManager()
    vistos = []

    async def handler_async(topic, payload):
        await asyncio.sleep(0)
        vistos.append(("async", payload))

    mgr.on_message("gateway/cmd", handler_async)
    mgr.on_message("gateway/cmd", lambda t, p: vistos.append(("sync", p)))

    await mgr._dispatch(mensaje("gateway/cmd", b'{"n": 1}'))

    assert ("async", {"n": 1}) in vistos
    assert ("sync", {"n": 1}) in vistos


async def test_un_handler_roto_no_impide_a_los_demas():
    mgr = MQTTManager()
    vistos = []

    def handler_roto(topic, payload):
        raise RuntimeError("boom")

    mgr.on_message("gateway/cmd", handler_roto)
    mgr.on_message("gateway/cmd", lambda t, p: vistos.append(p))

    await mgr._dispatch(mensaje("gateway/cmd", b"ok"))   # no debe propagar

    assert vistos == ["ok"]


async def test_mensaje_sin_handler_no_rompe():
    mgr = MQTTManager()

    await mgr._dispatch(mensaje("gateway/desconocido", b"x"))


# --------------------------------------------------------------------------
# listen() y messages()
# --------------------------------------------------------------------------

async def test_listen_despacha_los_mensajes_entrantes(monkeypatch):
    mgr = MQTTManager()
    mgr._client = cliente_con_mensajes([
        mensaje("gateway/cmd", b'{"accion": "start"}'),
        mensaje("gateway/cmd", b'{"accion": "stop"}'),
    ])

    recibidos = []
    mgr.on_message("gateway/cmd", lambda t, p: recibidos.append(p["accion"]))

    # Corta el bucle tras agotar el flujo, en vez de reconectar
    monkeypatch.setattr(mgr, "_reconnect", AsyncMock(side_effect=asyncio.CancelledError))

    with pytest.raises(asyncio.CancelledError):
        await mgr.listen(reconnect_delay=0)

    assert recibidos == ["start", "stop"]


async def test_listen_reconecta_si_se_cae_la_conexion(monkeypatch):
    mgr = MQTTManager()
    mgr._client = cliente_con_mensajes(
        [mensaje("gateway/cmd", b"1")],
        error_al_final=aiomqtt.MqttError("broker caído"),
    )

    recibidos = []
    mgr.on_message("gateway/cmd", lambda t, p: recibidos.append(p))

    reconexiones = []

    async def fake_reconnect():
        reconexiones.append(True)
        raise asyncio.CancelledError   # corta el bucle en la 1ª reconexión

    monkeypatch.setattr(mgr, "_reconnect", fake_reconnect)

    with pytest.raises(asyncio.CancelledError):
        await mgr.listen(reconnect_delay=0)

    assert recibidos == [1]        # procesó lo que llegó antes del corte
    assert reconexiones == [True]  # y reaccionó a la caída


async def test_listen_se_detiene_al_cancelar_la_tarea():
    mgr = MQTTManager()

    async def flujo_infinito():
        while True:
            await asyncio.sleep(0.01)
            yield mensaje("gateway/cmd", b"1")

    cliente = AsyncMock()
    type(cliente).messages = property(lambda self: flujo_infinito())
    mgr._client = cliente

    tarea = asyncio.create_task(mgr.listen())
    await asyncio.sleep(0.05)
    tarea.cancel()

    with pytest.raises(asyncio.CancelledError):
        await tarea


async def test_messages_devuelve_topic_y_payload_decodificado():
    mgr = MQTTManager()
    mgr._client = cliente_con_mensajes([
        mensaje("gateway/a", b'{"v": 1}'),
        mensaje("gateway/b", b"texto"),
    ])

    recibidos = [item async for item in mgr.messages()]

    assert recibidos == [("gateway/a", {"v": 1}), ("gateway/b", "texto")]


async def test_messages_sin_cliente_lanza():
    mgr = MQTTManager()

    with pytest.raises(RuntimeError):
        [item async for item in mgr.messages()]
