"""Los tres valores que el equipo se inventa a sí mismo, al instalarse.

`MQTT_CLIENT_ID`, `INFLUXDB_ADMIN_PASSWORD` e `INFLUXDB_TOKEN` no salen del
CRM ni de ningún panel: los crea este gateway, al azar, y no salen de aquí. El
CRM los tiene en su tabla de configuración con el valor vacío justamente para
decir eso — el nombre viaja, el valor no.

Escribirlos a mano es la forma en que aparecen dos gateways con el mismo
`MQTT_CLIENT_ID`, que es el peor caso: no falla al arrancar, los dos se
conectan al broker y se echan mutuamente en bucle, y el síntoma que se ve es
telemetría que llega a saltos.

La lógica vive aquí y no en el script para poder probarla: `scripts/` es sólo
la línea de comandos.
"""

import contextlib
import re
import secrets
from collections.abc import Callable
from pathlib import Path

# La raíz del proyecto: src/Core/device_secrets.py -> tres niveles arriba.
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# Prefijos: son los que ya usan los equipos instalados. Un identificador con
# forma reconocible se ubica de un vistazo en los logs del broker, que es
# donde hay que mirar cuando dos equipos pelean por la misma conexión.
CLIENT_ID_PREFIX = "gatewayems_"
CLIENT_ID_BYTES = 4

ADMIN_PASSWORD_PREFIX = "gateway_ems_"
# Alfabeto sin 0/O/1/l/I: esta contraseña se teclea en la interfaz de InfluxDB
# y a veces se dicta por teléfono.
_ALFABETO = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ADMIN_PASSWORD_LENGTH = 16

# 48 bytes en base64 url-safe son 64 caracteres: la longitud recomendada para
# un token de InfluxDB, y la que ya tienen los equipos instalados.
INFLUX_TOKEN_BYTES = 48


def generate_mqtt_client_id() -> str:
    """Identificador de la conexión al broker. Distinto en cada llamada."""
    return CLIENT_ID_PREFIX + secrets.token_hex(CLIENT_ID_BYTES)


def generate_influx_admin_password() -> str:
    """Contraseña del InfluxDB local."""
    cuerpo = "".join(
        secrets.choice(_ALFABETO) for _ in range(ADMIN_PASSWORD_LENGTH)
    )
    return ADMIN_PASSWORD_PREFIX + cuerpo


def generate_influx_token() -> str:
    """Token del InfluxDB local. Máquina a máquina: nadie lo teclea."""
    return secrets.token_urlsafe(INFLUX_TOKEN_BYTES)


# Clave -> cómo se genera, y si puede mostrarse al terminar. El identificador
# de cliente no es un secreto: es lo que hay que leer para reconocer al equipo.
GENERADORES: tuple[tuple[str, Callable[[], str], bool], ...] = (
    ("MQTT_CLIENT_ID", generate_mqtt_client_id, True),
    ("INFLUXDB_ADMIN_PASSWORD", generate_influx_admin_password, False),
    ("INFLUXDB_TOKEN", generate_influx_token, False),
)

CLAVES = tuple(clave for clave, _, _ in GENERADORES)

BLOQUE_TITULO = "# --- Valores propios del equipo (generados) ---"


class EnvFileMissingError(RuntimeError):
    """No hay `.env` que completar."""


def _patron(clave: str) -> re.Pattern[str]:
    """Reconoce la línea de una clave, con o sin espacios alrededor del `=`."""
    return re.compile(rf"^\s*{re.escape(clave)}\s*=(?P<valor>.*)$")


def valor_actual(lineas: list[str], clave: str) -> str | None:
    """El valor que ya tiene la clave, o None si la clave no está."""
    patron = _patron(clave)
    for linea in lineas:
        encontrada = patron.match(linea)
        if encontrada is not None:
            return encontrada.group("valor").strip()
    return None


def aplicar_valores(lineas: list[str], valores: dict[str, str]) -> list[str]:
    """El archivo con los valores puestos y todo lo demás intacto.

    Una clave que ya figura se reescribe en su sitio: moverla al final
    cambiaría el archivo más de lo necesario, y un `.env` es de los ficheros
    que menos se miran antes de arrancar. Una que no figura se añade al final,
    bajo un título, para que se vea de dónde salió.
    """
    resultado = list(lineas)
    pendientes: list[str] = []

    for clave, valor in valores.items():
        patron = _patron(clave)
        for indice, linea in enumerate(resultado):
            if patron.match(linea) is not None:
                # Sin comillas: docker-compose las pasa literales y el valor
                # llegaría a InfluxDB con las comillas pegadas.
                resultado[indice] = f"{clave}={valor}"
                break
        else:
            pendientes.append(f"{clave}={valor}")

    if pendientes:
        if resultado and resultado[-1].strip():
            resultado.append("")
        resultado.append(BLOQUE_TITULO)
        resultado.extend(pendientes)

    return resultado


def _escribir_atomico(path: Path, contenido: str) -> None:
    """Escribe por un temporal y renombra.

    Un `.env` a medias porque el proceso se cortó es peor que no haberlo
    tocado: el arranque falla en `Settings` con el nombre de una variable que
    no dice nada de esto.
    """
    temporal = path.with_name(path.name + ".tmp")
    temporal.write_text(contenido, encoding="utf-8")
    # Un modo que no se puede copiar no justifica no escribir el archivo.
    with contextlib.suppress(OSError):
        temporal.chmod(path.stat().st_mode & 0o7777)
    temporal.replace(path)


def generar_en(
    path: Path, *, force: bool = False, dry_run: bool = False
) -> tuple[dict[str, str], list[str]]:
    """Completa el `.env` y devuelve (lo generado, lo que ya estaba).

    No crea el archivo. Si no existe, lo que falta es copiar `.env.example` y
    cargar el resto: un `.env` con sólo estas tres claves dentro parece
    configurado y no arranca.
    """
    if not path.is_file():
        raise EnvFileMissingError(
            f"No existe {path}. Copia `.env.example` a `.env` y carga el resto "
            "de la configuración antes de ejecutar esto."
        )

    lineas = path.read_text(encoding="utf-8").splitlines()

    generados: dict[str, str] = {}
    conservados: list[str] = []
    for clave, generador, _ in GENERADORES:
        actual = valor_actual(lineas, clave)
        if actual and not force:
            conservados.append(clave)
            continue
        generados[clave] = generador()

    if generados and not dry_run:
        _escribir_atomico(path, "\n".join(aplicar_valores(lineas, generados)) + "\n")

    return generados, conservados
