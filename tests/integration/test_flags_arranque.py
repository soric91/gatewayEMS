"""
Modo autónomo: `MQTT_ACTIVE=false`.

El caso de uso es un gateway que sólo lee Modbus y guarda en su InfluxDB local.
Como MQTT transporta además el plano de control del CRM, apagarlo apaga las dos
cosas: ni publicación, ni escucha del CRM, ni heartbeat. Ese equipo se configura
entonces únicamente por su config.ini.

Lo que se comprueba aquí es que el apagado es de verdad —que no se construye ni
el cliente MQTT ni el del CRM, o sea que el gateway arranca sin broker— y que no
deja tras de sí una cola sin consumidor, que es el fallo silencioso de este
cambio: se llenaría hasta el tope y descartaría un lote en cada lectura.
"""
import asyncio
import configparser
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.Config.config import ConfigManager
from src.Core.config import settings
from src.Task.task import TaskManager

pytestmark = pytest.mark.integration

INI = (
    "[DEFAULT]\n"
    "loglevel = INFO\n"
    "logstdout = True\n"
    "logfile = src/Log/gateway_ems.log\n"
    "max_size_bytes = 1485760\n"
    "backup_count = 5\n"
    "sampleslog = False\n"
    "\n"
    "[MAINMODBUS]\n"
    "devicesnames = \n"
    "interval = 1\n"
    "start_hour = 0\n"
    "stop_hour = 23\n"
)

TAREAS_CON_MQTT = {
    "read_modbus", "process_queue", "publish_mqtt",
    "listen_mqtt", "fetch_config", "apply_config", "heartbeat",
}
TAREAS_AUTONOMO = {"read_modbus", "process_queue"}


@pytest.fixture
def ini(tmp_path: Path) -> Path:
    ruta = tmp_path / "config.ini"
    ruta.write_text(INI)
    return ruta


@pytest.fixture
def montar(ini):
    """
    Devuelve una función que monta un TaskManager con MQTT encendido o apagado.

    Cede también las clases parcheadas para poder comprobar si llegaron a
    instanciarse: es la única prueba de que no se tocó el broker.
    """
    def _montar(mqtt_activo: bool, monkeypatch):
        monkeypatch.setattr(settings, "MQTT_ACTIVE", mqtt_activo)

        cm = ConfigManager()
        cm.config = configparser.ConfigParser()
        cm.config_path = ini
        cm.config.read(ini)

        parches = patch("src.Task.task.MQTTManager"), \
            patch("src.Task.task.ModbusService"), \
            patch("src.Task.task.CrmClient")
        mqtt_cls, service_cls, crm_cls = (p.start() for p in parches)

        mqtt_cls.return_value = AsyncMock()
        service_cls.return_value = AsyncMock()
        crm_cls.return_value = AsyncMock()
        crm_cls.return_value.heartbeat = AsyncMock(
            return_value={"config_habilitada": False}
        )

        tm = TaskManager(cm)
        tm.config = cm
        return tm, mqtt_cls, crm_cls

    yield _montar
    patch.stopall()


# ---------------------------------------------------------------------------
# Apagado: ni broker ni CRM
# ---------------------------------------------------------------------------

async def test_no_se_construye_el_cliente_mqtt_ni_el_del_crm(montar, monkeypatch):
    """Si no se instancian, no hay conexión que hacer: arranca sin broker."""
    tm, mqtt_cls, crm_cls = montar(False, monkeypatch)

    assert await tm.initialize() is True

    mqtt_cls.assert_not_called()
    crm_cls.assert_not_called()
    assert tm.mqtt_manager is None
    assert tm.crm_client is None

    await tm.stop()


async def test_solo_arrancan_la_lectura_y_el_guardado(montar, monkeypatch):
    tm, _, _ = montar(False, monkeypatch)
    assert await tm.initialize() is True

    arranque = asyncio.create_task(tm.start_all_tasks())
    await asyncio.sleep(0.1)

    assert {t.get_name() for t in tm._tasks} == TAREAS_AUTONOMO

    await tm.stop_all_tasks()
    arranque.cancel()
    await asyncio.gather(arranque, return_exceptions=True)


async def test_no_queda_una_cola_de_mqtt_sin_consumidor(montar, monkeypatch):
    """
    El fallo silencioso de este cambio.

    `QueueManager` reparte a TODOS sus suscriptores. Un suscriptor 'mqtt'
    registrado cuya tarea no arranca acumula hasta el tope y a partir de ahí
    descarta un lote —y escribe un warning— en cada lectura, para siempre.
    """
    tm, _, _ = montar(False, monkeypatch)
    assert await tm.initialize() is True

    assert tm.queue_manager.subscribers == [tm.sub_influx]

    await tm.stop()


async def test_lo_que_se_lee_sigue_llegando_a_influxdb(montar, monkeypatch):
    """Apagar MQTT no puede tocar el camino que sí tiene que seguir vivo."""
    tm, _, _ = montar(False, monkeypatch)
    assert await tm.initialize() is True

    await tm.queue_manager.publish({"results": ["lectura"]})

    assert tm.queue_manager.qsize(tm.sub_influx) == 1
    assert tm.queue_manager.dropped_count(tm.sub_influx) == 0

    await tm.stop()


async def test_publicar_el_estado_no_revienta_sin_mqtt(montar, monkeypatch):
    tm, _, _ = montar(False, monkeypatch)
    assert await tm.initialize() is True

    await tm._publicar_estado()          # no debe lanzar

    await tm.stop()


# ---------------------------------------------------------------------------
# Encendido: todo como siempre
# ---------------------------------------------------------------------------

async def test_con_mqtt_activo_arranca_todo_como_antes(montar, monkeypatch):
    """El valor por defecto no cambia el comportamiento de hoy."""
    tm, mqtt_cls, crm_cls = montar(True, monkeypatch)
    assert await tm.initialize() is True

    mqtt_cls.assert_called_once()
    crm_cls.assert_called_once()
    assert tm.queue_manager.subscribers == [tm.sub_influx, tm.sub_mqtt]

    arranque = asyncio.create_task(tm.start_all_tasks())
    await asyncio.sleep(0.1)

    assert {t.get_name() for t in tm._tasks} == TAREAS_CON_MQTT

    await tm.stop_all_tasks()
    arranque.cancel()
    await asyncio.gather(arranque, return_exceptions=True)
