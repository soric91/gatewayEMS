#!/usr/bin/env python3
"""
Migra el histórico ya guardado en el InfluxDB local al InfluxDB del servidor.

Por qué existe aparte de la réplica automática del gateway: esa tarea arranca su
marca de agua en "ahora" y avanza hacia adelante, así que sube lo nuevo y nunca
lo viejo. Un equipo que lleva meses funcionando necesita otro camino.

Los dos caminos van en sentidos opuestos y con marcas distintas, a propósito:

    pasado  <--- este script (hacia atrás)  |  la tarea (hacia adelante) --->  futuro
                                          ahora

Así se pueden parar, matar o reanudar la migración sin que la réplica en vivo se
entere, y el servidor tiene datos recientes desde el primer minuto mientras el
histórico se va rellenando por detrás.

Reejecutar un tramo es inofensivo: en InfluxDB, mismo measurement + mismos tags
+ mismo timestamp SOBRESCRIBEN. Ante la duda, se repite.

Este script NO forma parte del gateway: no se importa desde ningún sitio y no
importa nada de `src/`. Es una herramienta de una vez, y se puede lanzar desde
cualquier máquina con acceso a los dos InfluxDB.

Uso típico, en este orden:

    # 1. Ver cuánto hay, sin escribir nada
    uv run scripts/backfill_servidor.py --dry-run

    # 2. Probar con un solo día y comprobarlo en el servidor
    uv run scripts/backfill_servidor.py --desde 2026-08-01 --hasta 2026-08-02

    # 3. Soltar el rango completo, dentro de tmux (puede tardar horas)
    uv run scripts/backfill_servidor.py --desde 2026-05-01

    # 4. Si se cortó, reanudar por donde iba
    uv run scripts/backfill_servidor.py --continuar
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

MEASUREMENT = "Modbus_Data"
TAGS = ("device_name", "device_id", "device_type", "identify_device")
COLUMNAS_DE_FLUX = frozenset(
    {"result", "table", "_start", "_stop", "_time", "_measurement"}
)

ESTADO_POR_DEFECTO = Path("scripts/.backfill_state.json")


def rfc3339(momento: datetime) -> str:
    """Instante en la forma que espera Flux: siempre UTC y terminado en 'Z'."""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

UNIDADES = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def duracion(texto: str) -> timedelta:
    """Convierte '30s', '15m', '1h' o '7d' en un timedelta."""
    match = re.fullmatch(r"(\d+)([smhd])", texto.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError(
            f"duración no reconocida: {texto!r} (usa 30s, 15m, 1h, 7d)"
        )

    cantidad, unidad = int(match.group(1)), match.group(2)
    if cantidad < 1:
        raise argparse.ArgumentTypeError("la duración tiene que ser positiva")

    return timedelta(**{UNIDADES[unidad]: cantidad})


def instante(texto: str) -> datetime:
    """Acepta '2026-05-01' o un ISO completo. Sin zona, se asume UTC."""
    try:
        valor = datetime.fromisoformat(texto.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"fecha no reconocida: {texto!r} (usa 2026-05-01 o 2026-05-01T10:00:00)"
        )
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def parsear_argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migra el histórico del InfluxDB local al del servidor central.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Orden recomendado:\n"
            "  1. --dry-run sobre el rango completo, para ver el volumen\n"
            "  2. un solo día, y comprobarlo en el servidor\n"
            "  3. el rango entero, dentro de tmux (puede tardar horas)\n"
            "  4. --continuar si se cortó\n"
        ),
    )
    p.add_argument("--desde", type=instante,
                   help="límite antiguo del tramo (por defecto, el dato más viejo)")
    p.add_argument("--hasta", type=instante,
                   help="límite reciente del tramo (por defecto, ahora)")
    p.add_argument("--ventana", type=duracion, default=timedelta(hours=1),
                   help="tamaño de cada trozo, en tiempo (por defecto 1h)")
    p.add_argument("--agregado", type=str, default="1m",
                   help="ventana de promediado (por defecto 1m). Ver --crudo")
    p.add_argument("--crudo", action="store_true",
                   help="sube cada lectura sin promediar. Es MUCHÍSIMO más volumen")
    p.add_argument("--pausa", type=float, default=2.0,
                   help="segundos entre trozos, para no saturar el enlace")
    p.add_argument("--dry-run", action="store_true",
                   help="cuenta lo que hay y no escribe nada")
    p.add_argument("--continuar", action="store_true",
                   help="reanuda desde el fichero de estado")
    p.add_argument("--estado", type=Path, default=ESTADO_POR_DEFECTO,
                   help=f"fichero de estado (por defecto {ESTADO_POR_DEFECTO})")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Entorno
# ---------------------------------------------------------------------------

def leer_entorno() -> dict:
    """Lee las credenciales de los dos InfluxDB del .env."""
    load_dotenv(".env.local")
    load_dotenv(".env")

    requeridas = {
        "local_url": "INFLUXDB_URL",
        "local_token": "INFLUXDB_TOKEN",
        "local_org": "INFLUXDB_ORG",
        "local_bucket": "INFLUXDB_BUCKET",
        "servidor_url": "INFLUXDB_SERVER_URL",
        "servidor_token": "INFLUXDB_SERVER_TOKEN",
        "servidor_org": "INFLUXDB_SERVER_ORG",
        "servidor_bucket": "INFLUXDB_SERVER_BUCKET",
        "gateway_uuid": "GATEWAY_UUID",
    }

    valores, faltan = {}, []
    for clave, variable in requeridas.items():
        valor = (os.getenv(variable) or "").strip()
        if not valor:
            faltan.append(variable)
        valores[clave] = valor

    if faltan:
        sys.exit(
            "❌ Faltan variables en el .env: " + ", ".join(faltan) +
            "\n   (las INFLUXDB_SERVER_* son las del servidor central)"
        )

    return valores


# ---------------------------------------------------------------------------
# Estado: hasta dónde se ha retrocedido
# ---------------------------------------------------------------------------

def leer_estado(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def guardar_estado(ruta: Path, mas_antiguo: datetime, subidos: int) -> None:
    """tmp + replace: un Ctrl-C a mitad no deja el estado a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    estado = leer_estado(ruta)
    estado["mas_antiguo_enviado"] = mas_antiguo.isoformat()
    estado["puntos_subidos"] = estado.get("puntos_subidos", 0) + subidos
    estado["actualizado"] = datetime.now(timezone.utc).isoformat()

    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(estado, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def flux_datos(bucket: str, desde: datetime, hasta: datetime, agregado: str) -> str:
    """
    Filas pivotadas del tramo, opcionalmente promediadas.

    Nota: `aggregateWindow(fn: mean)` sólo funciona con valores numéricos. Si
    algún equipo publicase una variable de texto, la consulta falla; para ese
    caso está `--crudo`.
    """
    promedio = (
        f'  |> aggregateWindow(every: {agregado}, fn: mean, createEmpty: false)\n'
        if agregado else ""
    )
    return (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: {rfc3339(desde)}, stop: {rfc3339(hasta)})\n'
        f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")\n'
        f'{promedio}'
        f'  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")\n'
        f'  |> sort(columns: ["_time"])\n'
    )


def flux_cuenta(bucket: str, desde: datetime, hasta: datetime) -> str:
    return (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: {rfc3339(desde)}, stop: {rfc3339(hasta)})\n'
        f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")\n'
        f'  |> group()\n'
        f'  |> count()\n'
    )


def flux_mas_antiguo(bucket: str) -> str:
    return (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: 0)\n'
        f'  |> filter(fn: (r) => r._measurement == "{MEASUREMENT}")\n'
        f'  |> group()\n'
        f'  |> first()\n'
    )


def punto_desde_fila(valores: dict, gateway_uuid: str):
    """
    Reconstruye un Point. Devuelve None si la fila no tiene ninguna medida.

    Se saltan los valores nulos: con mapas distintos entre equipos el pivot deja
    columnas vacías. Una fila con TODAS las medidas nulas produciría un punto que
    se serializa a cadena vacía, o sea una línea en blanco en la petición.
    """
    punto = Point(valores.get("_measurement", MEASUREMENT))

    for tag in TAGS:
        valor = valores.get(tag)
        if valor is not None:
            punto = punto.tag(tag, valor)

    # Sin esto el servidor no puede saber de qué equipo viene cada dato.
    punto = punto.tag("gateway_uuid", gateway_uuid)

    campos = 0
    for clave, valor in valores.items():
        if clave in COLUMNAS_DE_FLUX or clave in TAGS or valor is None:
            continue
        punto = punto.field(clave, valor)
        campos += 1

    return punto.time(valores["_time"]) if campos else None


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------

def migrar(args, entorno) -> int:
    local = InfluxDBClient(
        url=entorno["local_url"], token=entorno["local_token"],
        org=entorno["local_org"], timeout=120_000,
    )
    servidor = InfluxDBClient(
        url=entorno["servidor_url"], token=entorno["servidor_token"],
        org=entorno["servidor_org"], timeout=120_000,
    )
    query = local.query_api()
    escritura = servidor.write_api(write_options=SYNCHRONOUS)

    try:
        hasta = args.hasta or datetime.now(timezone.utc)
        estado = leer_estado(args.estado)

        if args.continuar:
            reanudar = estado.get("mas_antiguo_enviado")
            if not reanudar:
                sys.exit(f"❌ No hay nada que reanudar en {args.estado}")
            hasta = datetime.fromisoformat(reanudar)
            print(f"↩️  Reanudando: se había llegado hasta {hasta.isoformat()}")

        desde = args.desde or primer_dato(query, entorno["local_bucket"])
        if desde is None:
            print("✅ El InfluxDB local no tiene datos que migrar")
            return 0
        if desde >= hasta:
            print("✅ Nada pendiente: el tramo está vacío")
            return 0

        agregado = None if args.crudo else args.agregado
        print(
            f"📦 Tramo: {desde.isoformat()} → {hasta.isoformat()}\n"
            f"   Ventana: {args.ventana} | "
            f"{'CRUDO (sin promediar)' if args.crudo else f'promedio cada {agregado}'}\n"
            f"   Destino: {entorno['servidor_url']} / {entorno['servidor_bucket']}\n"
            f"   gateway_uuid: {entorno['gateway_uuid']}"
        )
        if args.dry_run:
            print("   (--dry-run: no se escribe nada)")

        return recorrer(args, entorno, query, escritura, desde, hasta, agregado)

    finally:
        local.close()
        servidor.close()


def primer_dato(query, bucket: str):
    """El timestamp más antiguo del bucket local, o None si está vacío."""
    tablas = query.query(flux_mas_antiguo(bucket))
    for tabla in tablas:
        for registro in tabla.records:
            return registro.get_time()
    return None


def recorrer(args, entorno, query, escritura, desde, hasta, agregado) -> int:
    """Va hacia atrás, ventana a ventana, desde `hasta` hasta `desde`."""
    total = 0
    fin = hasta
    trozos = 0

    while fin > desde:
        inicio = max(fin - args.ventana, desde)
        trozos += 1

        if args.dry_run:
            valores = query.query(flux_cuenta(entorno["local_bucket"], inicio, fin))
            cuenta = sum(
                registro.get_value()
                for tabla in valores for registro in tabla.records
            )
            total += cuenta
            print(f"   {inicio:%Y-%m-%d %H:%M} → {fin:%H:%M}  {cuenta:>10,} valores")
            fin = inicio
            continue

        flux = flux_datos(entorno["local_bucket"], inicio, fin, agregado)
        puntos = [
            punto
            for tabla in query.query(flux)
            for registro in tabla.records
            if (punto := punto_desde_fila(registro.values, entorno["gateway_uuid"]))
        ]

        if puntos:
            escritura.write(
                bucket=entorno["servidor_bucket"],
                org=entorno["servidor_org"],
                record=puntos,
            )
            total += len(puntos)

        # Sólo después de escribir: si el proceso muere aquí, la reanudación
        # repite este trozo, y repetir sobrescribe.
        guardar_estado(args.estado, inicio, len(puntos))
        print(
            f"   {inicio:%Y-%m-%d %H:%M} → {fin:%H:%M}  "
            f"{len(puntos):>8,} puntos  (acumulado {total:,})"
        )

        fin = inicio
        if args.pausa and fin > desde:
            time.sleep(args.pausa)

    if args.dry_run:
        print(f"\n📊 {total:,} valores en {trozos} trozo(s). No se escribió nada.")
        if not args.crudo:
            print("   Con --agregado el volumen real subido será bastante menor.")
    else:
        print(f"\n✅ {total:,} puntos subidos hasta {desde.isoformat()}")
        print(f"   Estado en {args.estado}")

    return total


def main(argv=None) -> int:
    args = parsear_argumentos(argv)
    entorno = leer_entorno()

    try:
        migrar(args, entorno)
    except KeyboardInterrupt:
        print(
            "\n⏹️  Interrumpido. El progreso está guardado: "
            "relanza con --continuar."
        )
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
