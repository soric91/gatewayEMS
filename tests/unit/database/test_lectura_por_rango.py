"""
Releer del InfluxDB local para replicar al servidor central.

Dos piezas: la conexión al segundo InfluxDB (misma clase, otros valores) y la
reconstrucción de los puntos a partir de las filas que devuelve Flux.

El detalle que más importa es el ida y vuelta: lo que se reconstruye tiene que
volver a serializarse igual que el punto original, porque de ahí sale la
idempotencia — mismo measurement, mismos tags y mismo timestamp sobrescriben en
vez de duplicar. Por eso los tests comparan `to_line_protocol()`, no atributos
sueltos.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.Core.config import settings
from src.Database.connection import InfluxDBConnection
from src.Database.repository import InfluxDBRepository
from src.Models.model import DeviceReadResult, EnergyPoint

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
UUID_EQUIPO = "7d8704bd-5fe0-4686-972e-a71febc718d7"


# --- la conexión al servidor -----------------------------------------------


def test_la_conexion_remota_usa_las_credenciales_del_servidor(monkeypatch):
    for nombre, valor in {
        "INFLUXDB_SERVER_URL": "https://central:8086",
        "INFLUXDB_SERVER_TOKEN": "token-servidor",
        "INFLUXDB_SERVER_ORG": "org-servidor",
        "INFLUXDB_SERVER_BUCKET": "telemetry_server",
    }.items():
        monkeypatch.setattr(settings, nombre, valor)

    remota = InfluxDBConnection.remota()

    assert remota._url == "https://central:8086"
    assert remota._token == "token-servidor"
    assert remota.org == "org-servidor"
    assert remota.bucket == "telemetry_server"


def test_la_conexion_remota_no_toca_la_local(monkeypatch):
    """Las dos conviven en el mismo proceso: no pueden compartir estado."""
    monkeypatch.setattr(settings, "INFLUXDB_SERVER_URL", "https://central:8086")
    monkeypatch.setattr(settings, "INFLUXDB_SERVER_BUCKET", "telemetry_server")

    local, remota = InfluxDBConnection(), InfluxDBConnection.remota()

    assert local._url == settings.INFLUXDB_URL
    assert local.bucket == settings.INFLUXDB_BUCKET
    assert remota._url != local._url


# --- reconstrucción de puntos ----------------------------------------------


def fila(**extra) -> dict:
    """Una fila tal como la devuelve Flux tras el pivot."""
    return {
        "result": "_result",
        "table": 0,
        "_start": AHORA - timedelta(minutes=15),
        "_stop": AHORA,
        "_time": AHORA,
        "_measurement": "Modbus_Data",
        "device_name": "Modbus_EMSIMONO_74",
        "device_id": "74",
        "device_type": "CT_Meter",
        "identify_device": UUID_EQUIPO,
        "Voltaje_A": 119.9,
        **extra,
    }


def repositorio(filas: list) -> InfluxDBRepository:
    """Repositorio cuya consulta devuelve las filas indicadas."""
    tabla = MagicMock()
    tabla.records = [MagicMock(values=f) for f in filas]

    query_api = MagicMock()
    query_api.query = AsyncMock(return_value=[tabla])

    conexion = MagicMock()
    conexion.bucket = "modbus_data"
    conexion.org = "test-org"
    conexion.get_query_api.return_value = query_api

    return InfluxDBRepository(_connection=conexion)


async def test_una_fila_se_reconstruye_como_el_punto_original():
    """El ida y vuelta completo: lo releído debe serializarse igual."""
    original = EnergyPoint.from_device_read_result(
        DeviceReadResult(
            device_name="Modbus_EMSIMONO_74",
            device_id=74,
            identify_device=UUID_EQUIPO,
            timestamp=AHORA,
            data={"Voltaje_A": 119.9},
            success=True,
            device_type="CT_Meter",
        )
    ).to_influx_point()

    releidos = await repositorio([fila()]).read_points_in_range(AHORA, AHORA)

    assert len(releidos) == 1
    assert releidos[0].to_line_protocol() == original.to_line_protocol()


async def test_las_columnas_vacias_del_pivot_no_se_convierten_en_fields():
    """Con mapas distintos entre equipos, el pivot deja huecos."""
    releidos = await repositorio(
        [fila(Corriente_A=None, Potencia=465.6)]
    ).read_points_in_range(AHORA, AHORA)

    linea = releidos[0].to_line_protocol()
    assert "Corriente_A" not in linea
    assert "Potencia=465.6" in linea


async def test_una_fila_sin_ningun_field_se_descarta():
    """Se serializaría a cadena vacía: sólo aportaría una línea en blanco."""
    sin_medidas = {k: v for k, v in fila().items() if k != "Voltaje_A"}

    assert await repositorio([sin_medidas]).read_points_in_range(AHORA, AHORA) == []


async def test_una_fila_con_todas_las_medidas_nulas_tambien_se_descarta():
    """
    El caso real del pivot: la fila de un equipo cuyo mapa no comparte ninguna
    variable con los demás sale con TODAS sus columnas de medida a null.

    Las columnas existen, así que hay que mirar el valor: contarlas como fields
    produce un punto que se serializa a cadena vacía y se cuela como línea en
    blanco en la petición.
    """
    todo_nulo = fila(Voltaje_A=None, Corriente_A=None)

    assert await repositorio([todo_nulo]).read_points_in_range(AHORA, AHORA) == []


async def test_el_timestamp_se_conserva():
    """Sin esto no hay idempotencia: reenviar duplicaría en vez de sobrescribir."""
    releidos = await repositorio([fila()]).read_points_in_range(AHORA, AHORA)

    assert releidos[0].to_line_protocol().endswith(
        str(int(AHORA.timestamp() * 1_000_000_000))
    )


async def test_los_tags_originales_viajan_todos():
    linea = (await repositorio([fila()]).read_points_in_range(AHORA, AHORA))[0]

    protocolo = linea.to_line_protocol()
    for esperado in (
        "device_name=Modbus_EMSIMONO_74",
        "device_id=74",
        "device_type=CT_Meter",
        f"identify_device={UUID_EQUIPO}",
    ):
        assert esperado in protocolo


# --- la consulta -----------------------------------------------------------


async def test_la_ventana_es_semiabierta_por_la_derecha():
    """
    `[desde, hasta)`: el `hasta` de una ventana es el `desde` de la siguiente.

    Es la semántica nativa de `range()` en Flux, y la que hace que encadenar
    ventanas no deje huecos ni solapes sin tocar nanosegundos.
    """
    repo = repositorio([fila()])
    hasta = AHORA + timedelta(minutes=15)

    await repo.read_points_in_range(AHORA, hasta)

    flux = repo._connection.get_query_api().query.await_args.args[0]
    assert (
        "range(start: 2026-08-06T12:00:00Z, stop: 2026-08-06T12:15:00Z)" in flux
    )


@pytest.mark.parametrize(
    "momento, esperado",
    [
        (AHORA, "2026-08-06T12:00:00Z"),
        (AHORA.replace(tzinfo=None), "2026-08-06T12:00:00Z"),
        (AHORA.astimezone(timezone(timedelta(hours=-5))), "2026-08-06T12:00:00Z"),
    ],
)
def test_los_instantes_se_escriben_en_utc_terminados_en_z(momento, esperado):
    """
    Forma canónica de RFC3339, la que usa InfluxDB en toda su documentación.

    Y normaliza la zona: un datetime en hora local consultaría un tramo
    desplazado cinco horas sin quejarse de nada. La máquina de campo corre en
    America/Bogota, así que no es un caso hipotético.
    """
    from src.Database.repository import rfc3339

    assert rfc3339(momento) == esperado


async def test_la_consulta_pivota_para_tener_una_fila_por_lectura():
    repo = repositorio([fila()])

    await repo.read_points_in_range(AHORA, AHORA)

    flux = repo._connection.get_query_api().query.await_args.args[0]
    assert 'pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")' in flux
    assert 'r._measurement == "Modbus_Data"' in flux
    assert 'from(bucket: "modbus_data")' in flux


async def test_un_rango_sin_datos_devuelve_una_lista_vacia():
    assert await repositorio([]).read_points_in_range(AHORA, AHORA) == []


async def test_sin_conexion_no_se_finge_que_no_hay_datos():
    """Una lista vacía haría avanzar la marca de agua saltándose el tramo."""
    conexion = MagicMock()
    conexion.get_query_api.return_value = None

    with pytest.raises(ConnectionError):
        await InfluxDBRepository(_connection=conexion).read_points_in_range(
            AHORA, AHORA
        )
