from datetime import datetime, timezone
from typing import List, Optional
from influxdb_client import Point
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api_async import WriteApiAsync
from src.Database.connection import InfluxDBConnection
from src.Utils.logging import get_logger
from dataclasses import dataclass, field


logger = get_logger(__name__)

# El measurement y los tags que escribe `EnergyPoint.to_influx_point()`. Al
# releer hay que saber cuáles de las columnas son tags: el resto son fields.
MEASUREMENT = "Modbus_Data"
TAGS = ("device_name", "device_id", "device_type", "identify_device")

# Columnas que Flux añade a cada fila y que no son datos nuestros.
COLUMNAS_DE_FLUX = frozenset(
    {"result", "table", "_start", "_stop", "_time", "_measurement"}
)


def rfc3339(momento: datetime) -> str:
    """
    Instante en la forma que espera Flux: siempre UTC y terminado en 'Z'.

    Normaliza además la zona horaria: un datetime ingenuo o en hora local
    consultaría un tramo desplazado sin quejarse de nada.
    """
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class InfluxDBRepository:

    _connection: InfluxDBConnection = field(default_factory=InfluxDBConnection)
    _write_api: Optional[WriteApiAsync] = None

    async def initialize(self) -> None:
        """
        Inicializa la conexión async.
        """
        await self._connection.connect()
        self._write_api = self._connection.get_write_api()

        if not self._write_api:
            logger.error("Failed to initialize InfluxDB write API.")
            raise ConnectionError("InfluxDB write API is not available.")

        logger.info("InfluxDBRepository initialized successfully.")


    async def save_points(self, points: List[Point]) -> None:
        """
        Guarda una lista de puntos en InfluxDB.

        El write es `await`: la petición HTTP viaja por aiohttp y cede el
        event loop mientras espera la respuesta, así que la lectura Modbus y
        la publicación MQTT siguen corriendo durante la escritura.
        """
        try:
            await self._write_api.write(
                bucket=self._connection.bucket,
                org=self._connection.org,
                record=points,
            )
            logger.info(f"Successfully saved {len(points)} points to InfluxDB.")
        except InfluxDBError as e:
            logger.error(f"Failed to save points to InfluxDB: {e}")
            raise

    async def read_points_in_range(
        self, desde: datetime, hasta: datetime
    ) -> List[Point]:
        """
        Relee las lecturas guardadas en el intervalo `[desde, hasta)`.

        El intervalo es semiabierto por la derecha, que es justo la semántica
        nativa de `range()` en Flux: el `hasta` de una ventana es el `desde` de
        la siguiente, sin huecos ni solapes y sin aritmética de nanosegundos.

        Por qué se trocea por TIEMPO y no por número de puntos: todas las
        lecturas de un mismo ciclo comparten el mismo timestamp (`read_all` lo
        calcula una vez por vuelta). Un corte "a los 5000 puntos" podría caer en
        medio de un grupo con el mismo instante, y la marca de agua avanzaría
        por encima del resto de ese grupo: un hueco silencioso, con unos equipos
        replicados y otros no. Cortando por tiempo el límite siempre cae entre
        grupos.
        """
        query_api = self._connection.get_query_api()
        if query_api is None:
            raise ConnectionError("InfluxDB query API no disponible")

        flux = f'''
from(bucket: "{self._connection.bucket}")
  |> range(start: {rfc3339(desde)}, stop: {rfc3339(hasta)})
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
        tablas = await query_api.query(flux, org=self._connection.org)

        puntos = [
            self._punto_desde_fila(registro.values)
            for tabla in tablas
            for registro in tabla.records
        ]
        return [punto for punto in puntos if punto is not None]

    @staticmethod
    def _punto_desde_fila(valores: dict) -> Optional[Point]:
        """
        Reconstruye un Point a partir de una fila ya pivotada.

        Se saltan los valores nulos: si dos equipos tienen mapas distintos, el
        `pivot` deja columnas vacías en las filas del que no tiene esa variable.
        El cliente ya los ignora al serializar, pero aquí importa para poder
        contarlos: una fila cuyas columnas de medida sean TODAS nulas no tiene
        ningún dato, y el punto resultante se serializaría a cadena vacía
        (`to_line_protocol() == ''`), aportando una línea en blanco a la
        petición y nada más. Por eso se descarta.
        """
        punto = Point(valores.get("_measurement", MEASUREMENT))

        for tag in TAGS:
            valor = valores.get(tag)
            if valor is not None:
                punto = punto.tag(tag, valor)

        campos = 0
        for clave, valor in valores.items():
            if clave in COLUMNAS_DE_FLUX or clave in TAGS or valor is None:
                continue
            punto = punto.field(clave, valor)
            campos += 1

        if not campos:
            return None

        # El timestamp se conserva tal cual: es lo que hace que reenviar un
        # tramo sobrescriba en vez de duplicar.
        return punto.time(valores["_time"])

    async def shutdown(self) -> None:
        """
        Cierra la conexión a InfluxDB.

        Pasos:
        1. Suelta el write API (WriteApiAsync no mantiene buffer propio:
           cada write() ya viajó al servidor antes de retornar)
        2. Cierra la sesión aiohttp del cliente
        3. Limpia referencias
        """
        try:
            self._write_api = None

            await self._connection.disconnect()

            logger.info("✅ InfluxDBRepository cerrado limpiamente")

        except Exception as e:
            logger.error(f"❌ Error cerrando InfluxDBRepository: {e}")
            raise
