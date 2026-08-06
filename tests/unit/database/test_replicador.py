"""
Réplica del InfluxDB local al servidor central.

Lo que se protege aquí es la marca de agua. Es la pieza donde un error no da
ningún síntoma: no hay excepción, no hay log rojo, simplemente el servidor
central se queda con huecos que nadie mira hasta meses después. De ahí que
casi todos los tests miren dónde acabó la marca, no sólo si se escribió.

Las tres reglas:
  1. la marca sólo avanza si la escritura fue bien,
  2. las ventanas encadenan sin huecos ni solapes,
  3. el borde derecho se queda por detrás del presente.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from influxdb_client import Point

from src.Core.config import settings
from src.Database.replicator import MARGEN_ESCRITURA, ServerReplicator

pytestmark = pytest.mark.unit

AHORA = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
VENTANA = timedelta(minutes=15)


def punto(valor: float = 119.9) -> Point:
    return (
        Point("Modbus_Data")
        .tag("device_name", "Modbus_EMSIMONO_74")
        .field("Voltaje_A", valor)
        .time(AHORA)
    )


@pytest.fixture
def replicador(tmp_path: Path, monkeypatch):
    """
    Replicador con los dos repositorios simulados y el reloj congelado.

    El reloj se fija para poder razonar sobre los bordes de las ventanas: sin
    eso, "hasta dónde llegó la marca" depende de cuánto tardó el test.
    """
    def _crear(puntos_por_ventana=None, ahora=AHORA):
        local = MagicMock()
        local.read_points_in_range = AsyncMock(
            side_effect=puntos_por_ventana
            if isinstance(puntos_por_ventana, list)
            else (lambda *_: [punto()] if puntos_por_ventana is None else [])
        )

        remoto = MagicMock()
        remoto.initialize = AsyncMock()
        remoto.save_points = AsyncMock()
        remoto.shutdown = AsyncMock()

        rep = ServerReplicator(
            _local=local,
            _remoto=remoto,
            state_dir=tmp_path / "remote",
            _ventana=VENTANA,
        )
        monkeypatch.setattr(rep, "_ahora", staticmethod(lambda: ahora))
        return rep

    return _crear


def marca_guardada(rep: ServerReplicator) -> datetime:
    return datetime.fromisoformat(
        json.loads(rep.state_file.read_text())["ultimo_enviado"]
    )


# --- la marca de agua ------------------------------------------------------


async def test_sin_estado_previo_no_se_sube_el_historico_entero(replicador):
    """
    Un equipo con meses de datos no puede intentar subirlos en su primer ciclo.

    Para eso está el script de migración, que va por otro camino y con su
    propio estado.
    """
    rep = replicador()

    assert rep.marca() == AHORA - VENTANA


async def test_la_marca_avanza_tras_una_escritura_correcta(replicador):
    rep = replicador()

    await rep.run_once()

    assert marca_guardada(rep) == AHORA - MARGEN_ESCRITURA


async def test_si_la_escritura_falla_la_marca_no_se_mueve(replicador):
    """El ciclo siguiente tiene que reintentar el MISMO tramo."""
    rep = replicador()
    rep._remoto.save_points.side_effect = ConnectionError("servidor caído")

    with pytest.raises(ConnectionError):
        await rep.run_once()

    assert not rep.state_file.exists(), "se dio por replicado un tramo que no subió"


async def test_si_la_lectura_local_falla_la_marca_tampoco_se_mueve(replicador):
    rep = replicador()
    rep._local.read_points_in_range.side_effect = RuntimeError("influx local")

    with pytest.raises(RuntimeError):
        await rep.run_once()

    assert not rep.state_file.exists()


async def test_una_marca_ilegible_no_deja_el_gateway_atascado(replicador):
    """Mejor perder un tramo que no volver a replicar nunca."""
    rep = replicador()
    rep.state_dir.mkdir(parents=True)
    rep.state_file.write_text("{ esto no es json")

    assert rep.marca() == AHORA - VENTANA


async def test_la_marca_se_escribe_de_forma_atomica(replicador):
    """tmp + replace: un corte de luz a mitad no deja la marca a medias."""
    rep = replicador()

    await rep.run_once()

    assert json.loads(rep.state_file.read_text())["ultimo_enviado"]
    assert not list(rep.state_dir.glob("*.tmp")), "quedó un temporal sin renombrar"


# --- las ventanas ----------------------------------------------------------


async def test_las_ventanas_encadenan_sin_huecos_ni_solapes(replicador):
    """
    El `hasta` de una ventana es exactamente el `desde` de la siguiente.

    Un hueco pierde datos y un solape los reenvía; lo segundo es inofensivo
    (sobrescribe), lo primero no se detecta nunca.
    """
    rep = replicador(ahora=AHORA + timedelta(hours=1))
    rep._guardar_marca(AHORA - VENTANA)

    await rep.run_once()

    rangos = [c.args for c in rep._local.read_points_in_range.await_args_list]
    assert len(rangos) > 1, "una hora de atraso tiene que dar varias ventanas"
    for (_, fin), (siguiente_inicio, _) in zip(rangos, rangos[1:]):
        assert fin == siguiente_inicio


async def test_el_borde_derecho_se_queda_por_detras_del_presente(replicador):
    """
    Leer el instante que se está escribiendo daría una lectura parcial, y la
    marca avanzaría por encima de lo que aún no había llegado.
    """
    rep = replicador()

    await rep.run_once()

    _, ultimo_fin = rep._local.read_points_in_range.await_args.args
    assert ultimo_fin == AHORA - MARGEN_ESCRITURA


async def test_un_atasco_largo_sube_por_ventanas_no_de_golpe(replicador):
    """Seis horas de corte no pueden convertirse en una sola petición gigante."""
    rep = replicador(ahora=AHORA + timedelta(hours=6))
    rep._guardar_marca(AHORA)

    await rep.run_once()

    llamadas = rep._local.read_points_in_range.await_args_list
    assert len(llamadas) == 24              # 6 h / 15 min
    for inicio, fin in (c.args for c in llamadas):
        assert fin - inicio <= VENTANA


async def test_sin_nada_nuevo_no_se_escribe_en_el_servidor(replicador):
    rep = replicador(puntos_por_ventana=[])
    rep._guardar_marca(AHORA - MARGEN_ESCRITURA)

    assert await rep.run_once() == 0
    rep._remoto.save_points.assert_not_awaited()


async def test_una_ventana_vacia_no_frena_a_las_siguientes(replicador):
    """Un hueco sin datos (equipo parado) no puede atascar la marca."""
    rep = replicador(
        puntos_por_ventana=[[], [punto()], []],
        ahora=AHORA + timedelta(minutes=45),
    )
    rep._guardar_marca(AHORA)

    assert await rep.run_once() == 1
    assert marca_guardada(rep) > AHORA


# --- lo que llega al servidor ----------------------------------------------


async def test_cada_punto_viaja_con_el_uuid_del_gateway(replicador, monkeypatch):
    """
    Sin este tag el servidor central no puede saber de qué equipo es cada dato,
    que es justo para lo que existe la réplica.
    """
    monkeypatch.setattr(settings, "GATEWAY_UUID", "5ed37c34-2b2d-47b4-858f-ae401a6f9d5a")
    rep = replicador()

    await rep.run_once()

    enviados = rep._remoto.save_points.await_args.args[0]
    assert "gateway_uuid=5ed37c34-2b2d-47b4-858f-ae401a6f9d5a" in (
        enviados[0].to_line_protocol()
    )


async def test_los_datos_originales_no_se_alteran(replicador):
    """Se añade un tag; ni el measurement, ni los fields, ni la hora cambian."""
    rep = replicador()

    await rep.run_once()

    linea = rep._remoto.save_points.await_args.args[0][0].to_line_protocol()
    assert linea.startswith("Modbus_Data,")
    assert "Voltaje_A=119.9" in linea
    assert linea.endswith(str(int(AHORA.timestamp() * 1_000_000_000)))


# --- conexión con el servidor ----------------------------------------------


async def test_solo_se_conecta_una_vez(replicador):
    """El coste de conexión no se paga en cada ciclo."""
    rep = replicador()

    await rep.run_once()
    await rep.run_once()

    rep._remoto.initialize.assert_awaited_once()


async def test_tras_un_fallo_se_vuelve_a_conectar(replicador):
    """
    La sesión aiohttp de un cliente que falló no se puede reutilizar.

    Sin esto, un corte de red dejaba la réplica reintentando para siempre sobre
    una sesión muerta.
    """
    rep = replicador()
    await rep.run_once()

    rep.marcar_desconectado()
    await rep.run_once()

    assert rep._remoto.initialize.await_count == 2


async def test_cerrar_sin_haber_conectado_no_hace_nada(replicador):
    rep = replicador()

    await rep.shutdown()

    rep._remoto.shutdown.assert_not_awaited()
