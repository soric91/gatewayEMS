"""
Tests de la capa InfluxDB tras migrar al cliente ASYNC nativo (aiohttp).

BUG CORREGIDO: `InfluxDBClient` + `write_options=SYNCHRONOUS` hacía el POST
HTTP de forma bloqueante dentro de `async def save_points()`. Como el event
loop es de un solo hilo, cada escritura congelaba la lectura Modbus, la
publicación MQTT y el watchdog — hasta 10 s (el timeout) si InfluxDB no
respondía.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from influxdb_client import Point

from src.Database.connection import InfluxDBConnection
from src.Database.repository import InfluxDBRepository

pytestmark = pytest.mark.unit


def cliente_falso(ping_ok=True, ping_error=None):
    """Doble del InfluxDBClientAsync: ping/close async, write_api síncrono."""
    cliente = MagicMock()
    cliente.ping = AsyncMock(return_value=ping_ok, side_effect=ping_error)
    cliente.close = AsyncMock()
    cliente.write_api = MagicMock(return_value=AsyncMock())
    return cliente


@pytest.fixture
def conexion(monkeypatch):
    """InfluxDBConnection con cliente falso y sin esperas entre reintentos."""
    conn = InfluxDBConnection()
    conn._retry_delay = 0
    conn._creados = []

    def fake_build():
        cliente = cliente_falso()
        conn._creados.append(cliente)
        return cliente

    monkeypatch.setattr(conn, "_build_client", fake_build)
    return conn


# --------------------------------------------------------------------------
# El bug: bloqueo del event loop
# --------------------------------------------------------------------------

async def test_save_points_no_bloquea_el_event_loop():
    """
    Mientras se escribe en InfluxDB, otras tareas deben seguir corriendo.
    Con el cliente síncrono anterior el ticker se paraba en seco durante
    toda la escritura.
    """
    DURACION_WRITE = 0.2
    PERIODO_TICK = 0.02

    repo = InfluxDBRepository()
    repo._connection = MagicMock(bucket="b", org="o")

    async def write_lento(**kwargs):
        await asyncio.sleep(DURACION_WRITE)   # I/O de red que SÍ cede el loop

    repo._write_api = MagicMock()
    repo._write_api.write = write_lento

    marcas = []
    parar = asyncio.Event()

    async def ticker():
        while not parar.is_set():
            marcas.append(time.perf_counter())
            await asyncio.sleep(PERIODO_TICK)

    tarea = asyncio.create_task(ticker())
    await asyncio.sleep(PERIODO_TICK * 2)

    await repo.save_points([Point("m").field("v", 1.0)])

    parar.set()
    await tarea

    huecos = [(b - a) for a, b in zip(marcas, marcas[1:])]
    peor = max(huecos)

    # El ticker siguió latiendo durante la escritura de 200 ms
    assert peor < PERIODO_TICK * 3, f"event loop bloqueado {peor*1000:.0f} ms"
    assert len(marcas) >= DURACION_WRITE / PERIODO_TICK


def test_la_capa_usa_el_cliente_async_y_no_el_sincrono():
    """
    Guard de regresión: si alguien vuelve a `InfluxDBClient` + `SYNCHRONOUS`,
    o quita el `await` del write, esto falla. El test de responsividad del
    loop no puede detectarlo por sí solo, porque el doble de test siempre es
    awaitable.
    """
    import inspect

    from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
    from influxdb_client.client.write_api_async import WriteApiAsync
    import src.Database.connection as connection
    import src.Database.repository as repository

    assert connection.InfluxDBClientAsync is InfluxDBClientAsync
    assert not hasattr(connection, "SYNCHRONOUS")
    assert not hasattr(connection, "InfluxDBClient")

    # El write real de la librería es una corrutina, no una llamada bloqueante
    assert inspect.iscoroutinefunction(WriteApiAsync.write)

    assert "await self._write_api.write(" in inspect.getsource(
        repository.InfluxDBRepository.save_points
    )

    # Construcción del cliente síncrono y sus write_options: fuera.
    # (Se comprueba con paréntesis para no chocar con `InfluxDBClientAsync(`.)
    fuente_conexion = inspect.getsource(connection)
    assert "InfluxDBClient(" not in fuente_conexion
    assert "write_options=" not in fuente_conexion


async def test_save_points_escribe_en_el_bucket_y_org_correctos():
    repo = InfluxDBRepository()
    repo._connection = MagicMock(bucket="modbus_data", org="gateway_ems")
    repo._write_api = AsyncMock()

    puntos = [Point("Modbus_Data").field("VOLTAGE_A", 118.0)]
    await repo.save_points(puntos)

    repo._write_api.write.assert_awaited_once_with(
        bucket="modbus_data", org="gateway_ems", record=puntos
    )


async def test_save_points_propaga_error_de_influx():
    from influxdb_client.client.exceptions import InfluxDBError

    repo = InfluxDBRepository()
    repo._connection = MagicMock(bucket="b", org="o")
    repo._write_api = AsyncMock()
    repo._write_api.write.side_effect = InfluxDBError(message="bucket not found")

    with pytest.raises(InfluxDBError):
        await repo.save_points([Point("m").field("v", 1.0)])


# --------------------------------------------------------------------------
# Conexión
# --------------------------------------------------------------------------

async def test_connect_crea_el_cliente_y_el_write_api(conexion):
    assert await conexion.connect() is True

    assert conexion.is_connected() is True
    assert conexion.get_write_api() is not None
    conexion._creados[0].ping.assert_awaited_once()


async def test_el_cliente_se_crea_al_conectar_no_al_construir(monkeypatch):
    """
    El cliente async abre una sesión aiohttp, así que no puede construirse
    fuera de un event loop en marcha (antes se creaba en __post_init__).
    """
    llamadas = []
    monkeypatch.setattr(
        "src.Database.connection.InfluxDBClientAsync",
        lambda **kw: llamadas.append(kw) or cliente_falso(),
    )

    conn = InfluxDBConnection()
    assert conn.get_client() is None
    assert llamadas == []

    await conn.connect()

    assert conn.get_client() is not None
    assert llamadas[0]["timeout"] == 10_000  # milisegundos


async def test_connect_reintenta_y_acaba_conectando(conexion, monkeypatch):
    respuestas = iter([False, False, True])
    monkeypatch.setattr(
        conexion, "_health_check", AsyncMock(side_effect=lambda: next(respuestas))
    )

    assert await conexion.connect() is True
    # Un cliente nuevo por intento: la sesión aiohttp cerrada no se reutiliza
    assert len(conexion._creados) == 3
    assert conexion._creados[0].close.await_count == 1


async def test_connect_lanza_ConnectionError_tras_agotar_reintentos(conexion, monkeypatch):
    monkeypatch.setattr(conexion, "_health_check", AsyncMock(return_value=False))

    with pytest.raises(ConnectionError):
        await conexion.connect()

    assert conexion.is_connected() is False
    assert len(conexion._creados) == 3  # _max_retries


async def test_health_check_devuelve_False_si_ping_lanza(monkeypatch):
    """El ping del cliente async propaga la excepción; no devuelve False."""
    conn = InfluxDBConnection()
    conn._client = cliente_falso(ping_error=OSError("connection refused"))

    assert await conn._health_check() is False


async def test_disconnect_cierra_la_sesion(conexion):
    await conexion.connect()
    cliente = conexion.get_client()

    await conexion.disconnect()

    cliente.close.assert_awaited_once()
    assert conexion.get_client() is None
    assert conexion.get_write_api() is None
    assert conexion.is_connected() is False


# --------------------------------------------------------------------------
# Ciclo de vida del repositorio
# --------------------------------------------------------------------------

async def test_initialize_lanza_si_no_hay_write_api():
    repo = InfluxDBRepository()
    repo._connection = MagicMock()
    repo._connection.connect = AsyncMock(return_value=True)
    repo._connection.get_write_api = MagicMock(return_value=None)

    with pytest.raises(ConnectionError):
        await repo.initialize()


async def test_shutdown_cierra_la_conexion():
    repo = InfluxDBRepository()
    repo._connection = MagicMock()
    repo._connection.disconnect = AsyncMock()
    repo._write_api = AsyncMock()

    await repo.shutdown()

    repo._connection.disconnect.assert_awaited_once()
    assert repo._write_api is None
