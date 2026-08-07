"""
Réplica del InfluxDB local al InfluxDB del servidor central.

Cada gateway sube aquí sus lecturas para que el servidor tenga la foto de toda
la flota. Los puntos viajan con un tag `gateway_uuid` añadido, que es lo que
permite distinguir de qué equipo viene cada dato.

La forma de hacerlo es releer del InfluxDB **local** desde una marca de agua
guardada en disco, no acumular en memoria. El local ya es el almacén duradero,
así que hace de buffer gratis: un corte de red de horas se recupera entero
cuando vuelve el enlace, y un reinicio del proceso —que en un equipo de campo es
rutina— no pierde nada.

Todo esto se apoya en una propiedad de InfluxDB: mismo measurement, mismos tags
y mismo timestamp **sobrescriben**. Reenviar un tramo por duda no duplica, así
que ante cualquier fallo lo correcto es no mover la marca y repetir.
"""
import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.Core.config import settings
from src.Database.connection import InfluxDBConnection
from src.Database.repository import InfluxDBRepository
from src.Utils.logging import get_logger

logger = get_logger(__name__)

# Cuánto se queda atrás el borde derecho de la ventana. Sin este margen se
# leerían instantes que todavía se están escribiendo, y esa lectura parcial
# haría avanzar la marca por encima de lo que aún no había llegado.
MARGEN_ESCRITURA = timedelta(seconds=30)

# Tope de ventanas por ciclo. Un atasco largo se recupera en varios ciclos en
# vez de dejar la tarea horas dentro de la misma llamada.
VENTANAS_POR_CICLO = 50


@dataclass
class ServerReplicator:
    """Sube al servidor central lo que ya está guardado en el InfluxDB local."""

    _local: InfluxDBRepository
    _remoto: InfluxDBRepository = field(
        default_factory=lambda: InfluxDBRepository(
            _connection=InfluxDBConnection.remota()
        )
    )
    state_dir: Path = field(
        default_factory=lambda: Path("src/Database/remote").resolve()
    )
    _ventana: timedelta = field(
        default_factory=lambda: timedelta(
            minutes=settings.INFLUXDB_SERVER_INTERVAL_MINUTES
        )
    )
    _conectado: bool = field(init=False, default=False)

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    # --- marca de agua ---------------------------------------------------

    def load_state(self) -> Dict[str, Any]:
        """Hasta dónde se ha replicado. Vacío la primera vez."""
        try:
            return json.loads(self.state_file.read_text())
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.warning(
                "⚠️ state.json de la réplica ilegible, se empieza desde ahora"
            )
            return {}

    def marca(self) -> datetime:
        """
        Instante desde el que hay que replicar.

        Sin marca previa se arranca en `ahora - una ventana`: un gateway con
        meses de datos guardados no puede intentar subirlos todos en su primer
        ciclo. Para eso está el script de migración, que va por otro camino y
        con su propio estado.
        """
        guardada = self.load_state().get("ultimo_enviado")
        if guardada:
            try:
                return datetime.fromisoformat(guardada)
            except ValueError:
                logger.warning(
                    f"⚠️ Marca de réplica ilegible ({guardada!r}), "
                    f"se empieza desde ahora"
                )

        return self._ahora() - self._ventana

    def _guardar_marca(self, hasta: datetime) -> None:
        """Escribe por tmp + replace: un corte a mitad no deja la marca rota."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        estado = self.load_state()
        estado["ultimo_enviado"] = hasta.isoformat()
        estado["actualizado"] = self._ahora().isoformat()

        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(estado, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    @staticmethod
    def _ahora() -> datetime:
        return datetime.now(timezone.utc)

    # --- ciclo de replicación --------------------------------------------

    async def _asegurar_conexion(self) -> None:
        """
        Conecta al servidor la primera vez, o tras un fallo.

        Se hace aquí y no al arrancar el proceso a propósito: que el servidor
        central esté caído no puede impedir que el gateway lea Modbus y guarde
        en local, que es lo que no puede dejar de funcionar.
        """
        if self._conectado:
            return

        await self._remoto.initialize()
        self._conectado = True
        logger.info("✅ Conectado al InfluxDB del servidor central")

    async def run_once(self) -> int:
        """
        Replica las ventanas pendientes. Devuelve cuántos puntos subió.

        Recorre hacia adelante ventana a ventana y sólo mueve la marca cuando la
        escritura ha ido bien. Si algo falla, la marca se queda donde estaba y el
        ciclo siguiente reintenta exactamente el mismo tramo.
        """
        await self._asegurar_conexion()

        desde = self.marca()
        total = 0

        for _ in range(VENTANAS_POR_CICLO):
            limite = self._ahora() - MARGEN_ESCRITURA
            if desde >= limite:
                break

            hasta = min(desde + self._ventana, limite)

            puntos = await self._local.read_points_in_range(desde, hasta)
            if puntos:
                for punto in puntos:
                    punto.tag("gateway_uuid", settings.GATEWAY_UUID)
                await self._remoto.save_points(puntos)
                total += len(puntos)

            # La marca avanza aunque la ventana estuviera vacía: no había nada
            # que subir, así que ese tramo está replicado por definición.
            self._guardar_marca(hasta)
            desde = hasta

        if total:
            logger.info(
                f"📤 Replicados {total} punto(s) al servidor central "
                f"(hasta {desde.isoformat()})"
            )
        else:
            logger.debug("📤 Nada pendiente de replicar")

        return total

    async def shutdown(self) -> None:
        """Cierra la conexión con el servidor. La local no es cosa suya."""
        if not self._conectado:
            return
        try:
            await self._remoto.shutdown()
        except Exception as e:
            logger.error(f"❌ Error cerrando la conexión con el servidor: {e}")
        finally:
            self._conectado = False

    def marcar_desconectado(self) -> None:
        """
        Obliga a reconectar en el ciclo siguiente.

        La sesión aiohttp de un cliente que ha fallado no se puede reutilizar:
        hay que descartarla y crear otra.
        """
        self._conectado = False
