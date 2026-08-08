#!/usr/bin/env python3
"""Genera los tres valores propios de este equipo y los deja en el `.env`.

Se ejecuta una vez, al instalar el gateway::

    uv run python scripts/generate_device_env.py

Genera `MQTT_CLIENT_ID`, `INFLUXDB_ADMIN_PASSWORD` e `INFLUXDB_TOKEN`. Son las
tres variables que no vienen del CRM: las crea el equipo, al azar, y no salen
de aquí.

Ejecutarlo de nuevo no rompe nada: una clave que ya tiene valor no se toca.
Regenerarlas exige `--force`, y eso significa que el equipo se reconecta al
broker con otra identidad y que el InfluxDB local se queda con credenciales
viejas hasta que se reinstale.

No importa `src.Core.config`: ese módulo construye `Settings`, que exige el
`.env` ya completo. Este script es justo lo que se ejecuta antes de que lo
esté.
"""

import argparse
import sys
from pathlib import Path

# Ejecutado como `python scripts/generate_device_env.py`, el directorio en
# sys.path es `scripts/`, no la raíz: sin esto no encuentra `src`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.Core.device_secrets import (  # noqa: E402
    DEFAULT_ENV_PATH,
    GENERADORES,
    EnvFileMissingError,
    generar_en,
)


def _informar(
    path: Path, generados: dict[str, str], conservados: list[str], *, dry_run: bool
) -> None:
    visibles = {clave for clave, _, mostrar in GENERADORES if mostrar}

    if generados:
        print(f"{'Se generarían' if dry_run else f'Escritas en {path}'}:")
        for clave, valor in generados.items():
            # Un secreto no se imprime: quedaría en el scrollback de la
            # terminal y en el log de la sesión. Su sitio es el archivo.
            tapado = "(no se muestra)" if dry_run else "(escrito, no se muestra)"
            print(f"  {clave}={valor if clave in visibles else tapado}")
    else:
        print("Nada que generar: las tres claves ya tienen valor.")

    if conservados:
        print("\nSin tocar, ya tenían valor:")
        for clave in conservados:
            print(f"  {clave}")
        print("Para regenerarlas: --force (el equipo cambia de identidad).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/generate_device_env.py",
        description=(
            "Genera MQTT_CLIENT_ID, INFLUXDB_ADMIN_PASSWORD e INFLUXDB_TOKEN "
            "y los escribe en el .env de este equipo."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="Archivo a completar (por defecto, el .env del proyecto).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerar aunque las claves ya tengan valor.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar qué se haría, sin escribir nada.",
    )
    args = parser.parse_args(argv)

    try:
        generados, conservados = generar_en(
            args.env_file, force=args.force, dry_run=args.dry_run
        )
    except EnvFileMissingError as exc:
        print(f"Error: {exc}")
        return 1

    _informar(args.env_file, generados, conservados, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
