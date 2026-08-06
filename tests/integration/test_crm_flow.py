"""
Integración del plano de control: del aviso MQTT hasta el acuse al CRM.

Recorre la cadena entera con un CRM de mentira (servidor aiohttp real) y los
archivos en un directorio temporal. Lo único doblado es Modbus, porque no hay
hardware.
"""
import asyncio
import configparser
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.Config.config import ConfigManager
from src.Core.config import settings
from src.Crm.applier import ConfigApplier
from src.Crm.client import CrmClient
from src.Task.task import TaskManager

pytestmark = pytest.mark.integration

UUID = settings.GATEWAY_UUID
VERSION = "a" * 64

CONFIG_CRM = {
    "gateway_uuid": UUID,
    "numero_serie": "gateway iot -s1",
    "firmware_version": "1.0.0",
    "generated_at": "2026-08-05T21:38:49.260470Z",
    "config_version": VERSION,
    "log": {"loglevel": "INFO"},
    "mainmodbus": {"interval": 5, "start_hour": 6, "stop_hour": 22},
    "devices": [
        {
            "name": "Medidor",                    # una sola palabra: el caso
            "identify_device": "178aa9d5-37b0-41a4-a4ae-34d5ce71231d",
            "device_type": "CT_Meter",            # que el split rompía
            "protocol": "RTU",
            "serialport": "/dev/ttyRS485",
            "baudrate": 9600,
            "device_id": 11,
            "modbusconnect": True,
            "modbusread": True,
            "blockreading": True,
            "map": {
                "Voltaje A": {"address": "0x2000", "data_type": "f", "gain": "1",
                              "unit": "V", "register_type": "holding"},
                "Voltaje B": {"address": "0x2002", "data_type": "f", "gain": "1",
                              "unit": "V", "register_type": "holding"},
            },
        }
    ],
}


class CrmFalso:
    def __init__(self, config: dict):
        self.config = config
        self.habilitada = True
        self.acks = []

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/v1/gateway/token", self._token)
        app.router.add_post(f"/api/v1/gateway/{UUID}/heartbeat", self._heartbeat)
        app.router.add_get(f"/api/v1/gateway/{UUID}/config", self._config)
        app.router.add_post(f"/api/v1/gateway/{UUID}/config/ack", self._ack)
        return app

    async def _token(self, request):
        return web.json_response(
            {"access_token": "t", "token_type": "bearer", "expires_in": 86400}
        )

    async def _heartbeat(self, request):
        return web.json_response({
            "gateway_uuid": UUID,
            "ultima_conexion": "2026-08-05T21:38:49Z",
            "config_habilitada": self.habilitada,
            "config_version_actual": self.config["config_version"],
        })

    async def _config(self, request):
        if not self.habilitada:
            return web.json_response({"detail": "not enabled"}, status=403)
        etag = f'"{self.config["config_version"]}"'
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers={"ETag": etag})
        return web.json_response(self.config, headers={"ETag": etag})

    async def _ack(self, request):
        cuerpo = await request.json()
        if cuerpo["config_version"] != self.config["config_version"]:
            return web.json_response({"detail": "stale"}, status=400)
        self.acks.append(cuerpo["config_version"])
        self.habilitada = False
        return web.json_response({"config_version_aplicada": cuerpo["config_version"]})


@pytest.fixture
async def crm():
    falso = CrmFalso(json.loads(json.dumps(CONFIG_CRM)))
    server = TestServer(falso.app())
    await server.start_server()
    falso.base_url = str(server.make_url("/api/v1"))
    yield falso
    await server.close()


@pytest.fixture
def gateway(tmp_path: Path, crm):
    """TaskManager con archivos en tmp y sin hardware ni InfluxDB."""
    config_ini = tmp_path / "config.ini"
    config_ini.write_text(
        "[DEFAULT]\nloglevel = INFO\nlogstdout = True\nbackup_count = 5\n\n"
        "[MAINMODBUS]\ndevicesnames =\ninterval = 1\nstart_hour = 0\nstop_hour = 23\n"
    )

    tm = TaskManager(ConfigManager())
    tm.mqtt_manager = AsyncMock()
    tm.modbus_service = AsyncMock()
    tm.modbus_app = MagicMock()
    tm.modbus_app.device_configs = {}
    tm.modbus_app.device_maps = {}
    tm.modbus_app._load_configs = MagicMock(return_value=True)
    tm.modbus_app._load_maps = MagicMock(return_value=True)

    tm.config_applier = ConfigApplier(
        config_path=config_ini,
        maps_dir=tmp_path / "maps",
        state_dir=tmp_path / "remote",
    )
    tm.crm_client = CrmClient(
        base_url=crm.base_url, gateway_uuid=UUID, credential="c", timeout=5
    )

    tm.fetch_queue.subscribe(tm.sub_worker)
    tm.apply_queue.subscribe(tm.sub_worker)
    return tm


async def _correr_ciclo(tm, vueltas: int = 1):
    """Arranca fetch+apply, espera a que drenen y las para."""
    tm._running = True
    tareas = [
        asyncio.create_task(tm.task_fetch_config()),
        asyncio.create_task(tm.task_apply_config()),
    ]
    for _ in range(200):
        if (tm.fetch_queue.qsize(tm.sub_worker) == 0
                and tm.apply_queue.qsize(tm.sub_worker) == 0):
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)

    tm._running = False
    for t in tareas:
        t.cancel()
    await asyncio.gather(*tareas, return_exceptions=True)
    await tm.crm_client.close()


async def test_del_aviso_mqtt_al_ack(gateway, crm):
    """Primera configuración: llega el aviso y el gateway queda configurado."""
    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "config_changed", "gateway_uuid": UUID, "config_version": VERSION},
    )

    await _correr_ciclo(gateway)

    # 1. config.ini escrito con lo que mandó el CRM
    ini = configparser.ConfigParser()
    ini.read(gateway.config_applier.config_path)
    assert ini["MAINMODBUS"]["devicesnames"] == "Medidor"
    assert ini["MAINMODBUS"]["interval"] == "5"
    assert ini["Medidor"]["serialport"] == "/dev/ttyRS485"
    assert ini["Medidor"]["modbus_function"] == "3"
    assert ini["DEFAULT"]["logstdout"] == "True"      # lo local se conserva

    # 2. mapa escrito
    mapa = json.loads((gateway.config_applier.maps_dir / "Medidor.json").read_text())
    assert set(mapa) == {"Voltaje_A", "Voltaje_B"}

    # 3. recarga en caliente, sin systemctl
    gateway.modbus_app._load_configs.assert_called()
    gateway.modbus_app._load_maps.assert_called()

    # 4. el CRM recibió el acuse
    assert crm.acks == [VERSION]

    # 5. estado persistido para la próxima vez
    estado = gateway.config_applier.load_state()
    assert estado["applied_version"] == VERSION
    assert estado["devices"] == ["Medidor"]


async def test_el_aviso_repetido_no_reconfigura(gateway, crm):
    """El aviso del CRM es retained: llega otra vez en cada reconexión."""
    evento = {"event": "config_changed", "gateway_uuid": UUID, "config_version": VERSION}

    await gateway._on_crm_event(settings.MQTT_TOPIC_CONFIG, evento)
    await _correr_ciclo(gateway)
    assert crm.acks == [VERSION]

    gateway.crm_client = CrmClient(
        base_url=crm.base_url, gateway_uuid=UUID, credential="c", timeout=5
    )
    gateway.modbus_app._load_configs.reset_mock()

    await gateway._on_crm_event(settings.MQTT_TOPIC_CONFIG, evento)
    await _correr_ciclo(gateway)

    assert crm.acks == [VERSION], "reconfiguró con el mismo aviso"
    gateway.modbus_app._load_configs.assert_not_called()


async def test_configuracion_invalida_no_toca_los_archivos(gateway, crm):
    """El CRM manda algo que no se puede aplicar: la config vigente sobrevive."""
    crm.config["devices"][0]["map"]["Voltaje A"]["data_type"] = "q"   # no existe
    original = gateway.config_applier.config_path.read_text()

    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "config_changed", "gateway_uuid": UUID, "config_version": VERSION},
    )
    await _correr_ciclo(gateway)

    assert gateway.config_applier.config_path.read_text() == original
    assert crm.acks == []
    assert gateway.config_applier.load_state() == {}
    gateway.mqtt_manager.publish.assert_awaited()      # reportó el fallo


async def test_si_la_recarga_falla_se_vuelve_a_la_configuracion_anterior(gateway, crm):
    """Rollback automático: sin comando desde el CRM."""
    # Primera configuración, correcta
    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "config_changed", "gateway_uuid": UUID, "config_version": VERSION},
    )
    await _correr_ciclo(gateway)
    buena = gateway.config_applier.config_path.read_text()

    # Segunda: válida en el papel, pero el gateway no la puede cargar
    version2 = "b" * 64
    crm.config["config_version"] = version2
    crm.config["mainmodbus"]["interval"] = 99
    crm.habilitada = True
    gateway.crm_client = CrmClient(
        base_url=crm.base_url, gateway_uuid=UUID, credential="c", timeout=5
    )
    gateway.modbus_app._load_maps = MagicMock(return_value=False)

    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "config_changed", "gateway_uuid": UUID, "config_version": version2},
    )
    await _correr_ciclo(gateway)

    assert gateway.config_applier.config_path.read_text() == buena
    assert version2 not in crm.acks
    assert gateway.config_applier.load_state()["applied_version"] == VERSION


async def test_el_heartbeat_dispara_la_descarga_sin_mqtt(gateway, crm):
    """Con el broker caído, el heartbeat es el que trae el trabajo."""
    gateway._running = True
    tareas = [
        asyncio.create_task(gateway.task_heartbeat()),
        asyncio.create_task(gateway.task_fetch_config()),
        asyncio.create_task(gateway.task_apply_config()),
    ]
    for _ in range(300):
        if crm.acks:
            break
        await asyncio.sleep(0.01)

    gateway._running = False
    for t in tareas:
        t.cancel()
    await asyncio.gather(*tareas, return_exceptions=True)
    await gateway.crm_client.close()

    assert crm.acks == [VERSION]


async def test_evento_de_otro_gateway_se_ignora(gateway):
    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "config_changed", "gateway_uuid": "otro-uuid",
         "config_version": VERSION},
    )

    assert gateway.fetch_queue.qsize(gateway.sub_worker) == 0


async def test_evento_desconocido_se_ignora(gateway):
    await gateway._on_crm_event(
        settings.MQTT_TOPIC_CONFIG,
        {"event": "firmware_update", "gateway_uuid": UUID},
    )

    assert gateway.fetch_queue.qsize(gateway.sub_worker) == 0


async def test_payload_basura_no_rompe_la_escucha(gateway):
    await gateway._on_crm_event(settings.MQTT_TOPIC_CONFIG, "no soy un dict")
    await gateway._on_crm_event(settings.MQTT_TOPIC_CONFIG, {"sin": "event"})

    assert gateway.fetch_queue.qsize(gateway.sub_worker) == 0
