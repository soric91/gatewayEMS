"""
Tests del bus de fan-out `QueueManager`.

BUG CORREGIDO: `task_process_queue` y `task_publish_mqtt` consumían la MISMA
`asyncio.Queue`. Como una `asyncio.Queue` entrega cada item a un único
consumidor, aproximadamente la mitad de los lotes acababan sólo en InfluxDB y
la otra mitad sólo en MQTT.
"""
import asyncio

import pytest

from src.Utils.utils import QueueManager

pytestmark = pytest.mark.unit

TIMEOUT = 1.0


async def consumir(qm: QueueManager, nombre: str):
    """Consume con timeout: una regresión de fan-out debe FALLAR, no colgarse."""
    return await asyncio.wait_for(qm.consume(nombre), TIMEOUT)


async def test_subscribe_es_idempotente():
    qm = QueueManager()

    primera = qm.subscribe("influxdb")
    segunda = qm.subscribe("influxdb")

    assert primera is segunda
    assert qm.subscribers == ["influxdb"]


async def test_publish_entrega_el_mismo_lote_a_todos_los_suscriptores():
    qm = QueueManager()
    qm.subscribe("influxdb")
    qm.subscribe("mqtt")

    lote = {"results": ["dato"], "success_count": 1, "total_count": 1}
    await qm.publish(lote)

    recibido_influx = await consumir(qm, "influxdb")
    recibido_mqtt = await consumir(qm, "mqtt")

    assert recibido_influx is lote
    assert recibido_mqtt is lote


async def test_regresion_cada_suscriptor_recibe_todos_los_lotes():
    """Con la cola compartida anterior, cada sink veía ~la mitad de los lotes."""
    qm = QueueManager()
    qm.subscribe("influxdb")
    qm.subscribe("mqtt")

    lotes = [{"n": i} for i in range(10)]
    for lote in lotes:
        await qm.publish(lote)

    influx = [await consumir(qm, "influxdb") for _ in range(10)]
    mqtt = [await consumir(qm, "mqtt") for _ in range(10)]

    # Todos los lotes, en orden, en ambos sinks
    assert influx == lotes
    assert mqtt == lotes
    assert qm.qsize("influxdb") == 0
    assert qm.qsize("mqtt") == 0


async def test_tres_suscriptores_reciben_todo():
    """Añadir un tercer sink no reparte los lotes: los recibe enteros."""
    qm = QueueManager()
    for nombre in ("influxdb", "mqtt", "alarmas"):
        qm.subscribe(nombre)

    await qm.publish({"n": 1})

    for nombre in ("influxdb", "mqtt", "alarmas"):
        assert await consumir(qm, nombre) == {"n": 1}


async def test_publish_sin_suscriptores_no_lanza():
    qm = QueueManager()

    await qm.publish({"n": 1})  # no debe lanzar

    assert qm.subscribers == []


async def test_consume_registra_al_suscriptor_al_vuelo():
    qm = QueueManager()

    tarea = asyncio.create_task(qm.consume("tardio"))
    await asyncio.sleep(0)  # deja que la tarea registre su cola

    await qm.publish({"n": 42})

    assert await asyncio.wait_for(tarea, timeout=1) == {"n": 42}


async def test_cola_llena_descarta_el_lote_mas_antiguo():
    qm = QueueManager(maxsize=2)
    qm.subscribe("lento")

    await qm.publish({"n": 1})
    await qm.publish({"n": 2})
    await qm.publish({"n": 3})  # desborda: descarta el {"n": 1}

    assert qm.qsize("lento") == 2
    assert qm.dropped_count("lento") == 1
    assert await consumir(qm, "lento") == {"n": 2}
    assert await consumir(qm, "lento") == {"n": 3}


async def test_suscriptor_lento_no_bloquea_al_rapido():
    """Un sink caído no puede frenar la adquisición ni a los demás sinks."""
    qm = QueueManager(maxsize=2)
    qm.subscribe("caido")   # nunca consume
    qm.subscribe("rapido")

    for i in range(5):
        # Si publish bloqueara al llenarse "caido", este await no volvería.
        await asyncio.wait_for(qm.publish({"n": i}), timeout=1)

    assert qm.dropped_count("caido") == 3
    assert qm.dropped_count("rapido") == 3
    # El sink rápido conserva siempre los lotes MÁS RECIENTES
    assert await consumir(qm, "rapido") == {"n": 3}
    assert await consumir(qm, "rapido") == {"n": 4}


async def test_unsubscribe_deja_de_recibir():
    qm = QueueManager()
    qm.subscribe("influxdb")
    qm.subscribe("mqtt")

    qm.unsubscribe("mqtt")
    await qm.publish({"n": 1})

    assert qm.subscribers == ["influxdb"]
    assert qm.qsize("influxdb") == 1
