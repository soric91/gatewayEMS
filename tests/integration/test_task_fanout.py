"""
Test de integración: las tres tareas del TaskManager sobre el bus de fan-out.

Verifica end-to-end que CADA lote leído por Modbus llega tanto a InfluxDB como
a MQTT. Antes del arreglo, ambos consumidores competían por la misma
`asyncio.Queue` y cada lote acababa en un solo sink.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.Config.config import ConfigManager
from src.Core.config import settings
from src.Models.model import DeviceReadResult
from src.Task.task import TaskManager

pytestmark = pytest.mark.integration

LOTES = 5
DISPOSITIVO = "Modbus_DTSU666"


def _resultado(indice: int) -> DeviceReadResult:
    return DeviceReadResult(
        device_name=f"{DISPOSITIVO}_11",
        device_section=DISPOSITIVO,
        device_id=11,
        identify_device="bf6a469f-4c2a-4402-9438-49a491ad2238",
        timestamp=datetime.now(timezone.utc),
        data={"VOLTAGE_A": 118.0 + indice},
        success=True,
        device_type="CT_Meter",
    )


@pytest.fixture
def task_manager():
    """TaskManager con sinks simulados, sin watchdog ni hardware ni red."""
    tm = TaskManager(ConfigManager())

    tm.interval = 0                     # loop de lectura sin espera
    tm._reading_devices = {DISPOSITIVO}
    tm.start_hour, tm.stop_hour = 0, 23  # siempre dentro de horario

    tm.modbus_service = AsyncMock()
    tm.mqtt_manager = AsyncMock()
    tm.modbus_app = AsyncMock()

    # Mismos suscriptores que registra initialize()
    tm.queue_manager.subscribe(tm.sub_influx)
    tm.queue_manager.subscribe(tm.sub_mqtt)

    return tm


async def _drenar_y_parar(tm, consumidores):
    """Espera a que se vacíen las colas y cancela los consumidores."""
    for _ in range(200):
        if tm.queue_manager.qsize(tm.sub_influx) == 0 and tm.queue_manager.qsize(tm.sub_mqtt) == 0:
            break
        await asyncio.sleep(0.01)

    await asyncio.sleep(0.05)  # margen para el último lote en vuelo

    for tarea in consumidores:
        tarea.cancel()
    await asyncio.gather(*consumidores, return_exceptions=True)


async def test_cada_lote_llega_a_influxdb_y_a_mqtt(task_manager):
    tm = task_manager
    lecturas = 0

    async def fake_read_all():
        nonlocal lecturas
        lecturas += 1
        if lecturas > LOTES:
            tm._running = False
            return []
        return [_resultado(lecturas)]

    tm.modbus_app.read_all = fake_read_all
    tm._running = True

    lectura = asyncio.create_task(tm.task_read_modbus_periodic())
    consumidores = [
        asyncio.create_task(tm.task_process_queue()),
        asyncio.create_task(tm.task_publish_mqtt()),
    ]

    await asyncio.wait_for(lectura, timeout=5)
    await _drenar_y_parar(tm, consumidores)

    assert tm.modbus_service.save_batch.await_count == LOTES
    assert tm.mqtt_manager.publish.await_count == LOTES

    # Los dos sinks vieron exactamente los mismos datos
    lotes_influx = [c.args[0][0].data for c in tm.modbus_service.save_batch.await_args_list]
    # publish(topic, payload): el payload es el segundo argumento
    lotes_mqtt = [c.args[1].data for c in tm.mqtt_manager.publish.await_args_list]
    topics = {c.args[0] for c in tm.mqtt_manager.publish.await_args_list}
    assert topics == {settings.MQTT_TOPIC_TLM}
    assert lotes_influx == lotes_mqtt
    assert len(lotes_influx) == LOTES


async def test_solo_se_publican_los_dispositivos_en_lectura(task_manager):
    """read_all devuelve dos dispositivos; sólo uno está habilitado para lectura."""
    tm = task_manager
    lecturas = 0

    ajeno = DeviceReadResult(
        device_name="Otro_Equipo_7",
        device_section="Otro_Equipo",
        device_id=7,
        identify_device="otro-uuid",
        timestamp=datetime.now(timezone.utc),
        data={"VOLTAGE_A": 1.0},
        success=True,
        device_type="Inverter",
    )

    async def fake_read_all():
        nonlocal lecturas
        lecturas += 1
        if lecturas > 1:
            tm._running = False
            return []
        return [_resultado(1), ajeno]

    tm.modbus_app.read_all = fake_read_all
    tm._running = True

    lectura = asyncio.create_task(tm.task_read_modbus_periodic())
    consumidores = [
        asyncio.create_task(tm.task_process_queue()),
        asyncio.create_task(tm.task_publish_mqtt()),
    ]

    await asyncio.wait_for(lectura, timeout=5)
    await _drenar_y_parar(tm, consumidores)

    guardados = tm.modbus_service.save_batch.await_args_list[0].args[0]
    assert [r.device_name for r in guardados] == [f"{DISPOSITIVO}_11"]
    assert tm.mqtt_manager.publish.await_count == 1


async def test_fuera_de_horario_no_publica_nada(task_manager):
    """Con la ventana horaria cerrada no debe llegar nada a los sinks."""
    tm = task_manager
    hora_actual = datetime.now().hour
    # Ventana de una hora que no contiene la hora actual
    tm.start_hour = (hora_actual + 2) % 24
    tm.stop_hour = tm.start_hour

    vueltas = 0

    async def fake_read_all():
        raise AssertionError("no debe leerse fuera de horario")

    async def parar_pronto(_):
        nonlocal vueltas
        vueltas += 1
        if vueltas >= 3:
            tm._running = False

    tm.modbus_app.read_all = fake_read_all
    tm._running = True

    import src.Task.task as task_module

    original_sleep = asyncio.sleep

    async def sleep_patched(delay):
        await parar_pronto(delay)
        await original_sleep(0)

    task_module.asyncio.sleep = sleep_patched
    try:
        lectura = asyncio.create_task(tm.task_read_modbus_periodic())
        await asyncio.wait_for(lectura, timeout=5)
    finally:
        task_module.asyncio.sleep = original_sleep

    assert tm.queue_manager.qsize(tm.sub_influx) == 0
    assert tm.queue_manager.qsize(tm.sub_mqtt) == 0
    assert tm.modbus_service.save_batch.await_count == 0
    assert tm.mqtt_manager.publish.await_count == 0
