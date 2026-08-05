<div align="center">

# ⚡ GatewayEMS

### Sistema de Gestión de Energía con Modbus e InfluxDB

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Code Coverage](https://img.shields.io/badge/coverage-84%25-brightgreen.svg)](htmlcov/index.html)
[![Tests](https://img.shields.io/badge/tests-139%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Code Style](https://img.shields.io/badge/code%20style-clean%20architecture-orange.svg)](docs/ARCHITECTURE.md)

**Un sistema profesional para la lectura, procesamiento y almacenamiento de datos Modbus en tiempo real**

[Características](#-características) •
[Instalación](#-instalación-rápida) •
[Arquitectura](#-arquitectura) •
[Configuración](#-configuración) •
[Documentación](#-documentación)

</div>

---

## 📋 Tabla de Contenidos

- [Características](#-características)
- [Arquitectura](#-arquitectura)
- [Requisitos](#-requisitos)
- [Instalación Rápida](#-instalación-rápida)
- [Configuración](#-configuración)
- [Uso](#-uso)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Testing](#-testing)
- [Documentación](#-documentación)
- [Contribuciones](#-contribuciones)
- [Licencia](#-licencia)

---

## ✨ Características

### 🔌 Conectividad Modbus Completa
- ✅ **Modbus RTU** - Comunicación serial RS485/RS232
- ✅ **Modbus TCP** - Comunicación sobre Ethernet
- ✅ **Conexiones persistentes** - Optimización de recursos
- ✅ **Reconexión automática** - Manejo robusto de errores
- ✅ **Múltiples dispositivos** - Gestión paralela de sensores

### 📊 Almacenamiento Time-Series
- ✅ **InfluxDB 2.x** - Base de datos optimizada para series temporales
- ✅ **Escritura asíncrona** - Alta performance sin bloqueos
- ✅ **Batch processing** - Agrupación eficiente de datos
- ✅ **Normalización automática** - Conversión de tipos y validación

### 🏗️ Arquitectura Profesional
- ✅ **Clean Architecture** - Separación clara de responsabilidades
- ✅ **Async/Await** - Programación asíncrona con AsyncIO
- ✅ **Producer-Consumer** - Patrón de colas para desacoplamiento
- ✅ **Type Hints** - Tipado estático con Pydantic
- ✅ **84% Test Coverage** - 139 tests automatizados

### ⚙️ Configuración Flexible
- ✅ **Config.ini dinámico** - Cambios en caliente con watchdog
- ✅ **Variables de entorno** - Gestión segura con .env
- ✅ **Mapas JSON** - Definición externa de registros Modbus
- ✅ **Horarios programables** - Control temporal de lecturas

### 📈 Monitoreo y Logs
- ✅ **Logging estructurado** - Trazabilidad completa
- ✅ **Health checks** - Verificación de conexiones
- ✅ **Graceful shutdown** - Cierre limpio de recursos
- ✅ **Docker ready** - Contenedorización incluida

---

## 🏛️ Arquitectura

GatewayEMS implementa **Clean Architecture** con separación de capas y principios SOLID:

```
┌─────────────────────────────────────────────────────────────────┐
│                         TASK MANAGER                            │
│                    (Orquestador Principal)                      │
│  • AsyncIO Event Loop                                           │
│  • Producer-Consumer Queue                                      │
│  • Watchdog Configuration Monitor                               │
└────────────┬────────────────────────────────────┬───────────────┘
             │                                    │
             ▼                                    ▼
    ┌────────────────┐                  ┌────────────────┐
    │  MODBUS APP    │                  │ MODBUS SERVICE │
    │  (Hardware)    │                  │ (Business)     │
    └────────┬───────┘                  └────────┬───────┘
             │                                    │
             ▼                                    ▼
    ┌────────────────┐                  ┌────────────────┐
    │ Device Clients │                  │   Repository   │
    │ • TCP Client   │                  │   (Database)   │
    │ • RTU Client   │                  └────────┬───────┘
    └────────────────┘                           │
                                                 ▼
                                        ┌────────────────┐
                                        │ InfluxDB Conn  │
                                        │ (Infrastructure)│
                                        └────────────────┘
```

### 🔄 Flujo de Datos

```
📡 Modbus Device → 🔌 Client → 📦 DeviceReadResult
                                        ↓
                               ⚙️ EnergyPoint (Domain)
                                        ↓
                               📊 InfluxDB Point
                                        ↓
                               💾 InfluxDB Database
```

**Capas de la arquitectura:**

1. **Capa de Presentación** (`src/Task/`) - Orquestación de tareas async
2. **Capa de Aplicación** (`src/Modbus/app.py`) - Lógica de comunicación Modbus
3. **Capa de Dominio** (`src/Models/`) - Modelos de negocio y validación
4. **Capa de Infraestructura** (`src/Database/`) - Persistencia en InfluxDB
5. **Capa de Configuración** (`src/Config/`, `src/Core/`) - Settings y watchdog

---

## 📦 Requisitos

### Software
- **Python** >= 3.12
- **InfluxDB** 2.x (incluido en Docker Compose)
- **uv** - Gestor de paquetes rápido (recomendado) o pip

### Hardware (Opcional)
- Dispositivos Modbus RTU/TCP (medidores de energía, sensores, etc.)
- Adaptador RS485 para Modbus RTU (ej: `/dev/ttyRS485`)

---

## 🚀 Instalación Rápida

### 1️⃣ Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/gatewayEMS.git
cd gatewayEMS
```

### 2️⃣ Instalar uv (si no lo tienes)

```bash
# En Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# En Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 3️⃣ Crear entorno virtual e instalar dependencias

```bash
# Crear entorno virtual con Python 3.12+
uv venv

# Activar el entorno virtual
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Instalar todas las dependencias (incluyendo las de testing)
uv sync --all-extras
```

### 4️⃣ Configurar variables de entorno

```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar .env con tus credenciales
nano .env
```

**Mínimo requerido en `.env`:**
```env
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=tu_token_generado
INFLUXDB_ORG=gateway_ems
INFLUXDB_BUCKET=modbus_data
INFLUXDB_ADMIN_USER=admin
INFLUXDB_ADMIN_PASSWORD=tu_password_seguro
INFLUXDB_RETENTION=90
```

### 5️⃣ Iniciar InfluxDB con Docker

```bash
# Iniciar servicios (InfluxDB)
docker-compose up -d

# Verificar que InfluxDB está corriendo
docker ps
```

### 6️⃣ Configurar dispositivos Modbus

Edita `data/config.ini` para agregar tus dispositivos:

```ini
[MAINMODBUS]
devicesnames = Modbus_DTSU666
interval = 5
start_hour = 0
stop_hour = 23

[Modbus_DTSU666]
identify_device = bf6a469f-4c2a-4402-9438-49a491ad2238
devicetype = CT_Meter
protocol = RTU
serialport = /dev/ttyRS485
baudrate = 9600
mapfile = src/Modbus/maps/Modbus_DTSU666.json
device_id = 11
modbusconnect = true
modbusread = true
```

### 7️⃣ Ejecutar el sistema

```bash
# Modo desarrollo
python main.py

# Modo producción con logs
python main.py 2>&1 | tee gateway.log
```

---

## ⚙️ Configuración

### 📝 Configuración Detallada de `config.ini`

La sección `[MAINMODBUS]` en el archivo `config.ini` controla los dispositivos Modbus y su configuración principal.

#### Variable `devicesnames`
- **Descripción:** Esta variable lista los nombres de los dispositivos que el sistema debe gestionar.
- **Funcionamiento:** Cada nombre listado en `devicesnames` debe tener su propia sección `[DEVICE_NAME]` en el archivo `config.ini`.
- **Importante:** Si un dispositivo está en `devicesnames` pero no tiene su propia sección, el sistema **no lo procesará**.

Ejemplo:
```ini
[MAINMODBUS]
devicesnames = Modbus_DTSU666, Device_2
```
En este ejemplo:
- El sistema intentará gestionar los dispositivos `Modbus_DTSU666` y `Device_2`.
- Deben existir secciones `[Modbus_DTSU666]` y `[Device_2]` en el archivo.

#### Variables `modbusconnect` y `modbusread`
Estas dos variables en las secciones de dispositivos controlan el comportamiento de cada dispositivo:

- **`modbusconnect`:**
  - Cuando está en `true`, el sistema intentará conectarse al dispositivo.
  - En `false`, el sistema no conecta con el dispositivo, aunque esté en `devicesnames`.

- **`modbusread`:**
  - Cuando está en `true`, el sistema leerá registros del dispositivo después de conectarse.
  - En `false`, el sistema se conectará pero no leerá datos.

Por defecto, ambas variables suelen estar configuradas en `true`.

#### Ejemplo de configuración completa:
```ini
[MAINMODBUS]
devicesnames = Modbus_DTSU666

[Modbus_DTSU666]
identify_device = bf6a469f-4c2a-4402-9438-49a491ad2238
devicetype = CT_Meter
protocol = RTU
serialport = /dev/ttyRS485
baudrate = 9600
mapfile = src/Modbus/maps/Modbus_DTSU666.json
device_id = 11
modbusconnect = true
modbusread = true
```

#### Notas importantes:
1. Si la sección `[DEVICE_NAME]` no existe, el sistema ignorará ese dispositivo.
2. **Errores comunes:**
   - Si `modbusconnect` está en `false`, el dispositivo no se conectará (aunque esté en `devicesnames`).
   - Si `modbusread` está en `false`, el sistema no realizará lecturas Modbus del dispositivo.


---

## 💡 Uso

### 🎯 Inicio Rápido

Una vez instalado y configurado:

```bash
# Activar entorno virtual
source .venv/bin/activate

# Iniciar el sistema
python main.py
```

### 📊 Monitoreo en Tiempo Real

El sistema mostrará logs con emojis indicadores:

```
✅ TaskManager inicializado
🔌 Conectando Modbus_DTSU666...
📖 Iniciando lectura de Modbus_DTSU666...
📥 Procesando lote de resultados: 1/1 exitosos
✅ Lote procesado y guardado en InfluxDB
```

### 🔄 Cambios en Caliente

El sistema detecta automáticamente cambios en `config.ini`:

```bash
# Editar configuración
nano data/config.ini

# El watchdog detectará los cambios y actualizará automáticamente
# No es necesario reiniciar el sistema
```

### 📈 Visualizar Datos en InfluxDB

1. Abre tu navegador en `http://localhost:8086`
2. Login con credenciales de `.env`
3. Ve a **Data Explorer**
4. Ejecuta una query Flux:

```flux
from(bucket: "modbus_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "energy_data")
  |> filter(fn: (r) => r.device_id == "11")
```

---

### Tipos de datos soportados en Modbus
El sistema soporta diferentes tipos de datos Modbus, los cuales definen cómo se interpretan los valores leídos de los registros. Los tipos disponibles son:

| Tipo de Dato | Código | Descripción                     |
|--------------|--------|---------------------------------|
| FLOAT        | `f`    | Número de punto flotante (32 bits). |
| INT16        | `h`    | Entero de 16 bits con signo.    |
| UINT16       | `H`    | Entero de 16 bits sin signo.    |
| INT32        | `i`    | Entero de 32 bits con signo.    |
| UINT32       | `I`    | Entero de 32 bits sin signo.    |

#### Notas importantes:
- **Direcciones:** Los `address` en los archivos JSON pueden ser en formato **decimal** o **hexadecimal** (por ejemplo, `0x2006` o `8198`). 
  - Si usas hexadecimal, asegúrate de incluir el prefijo `0x`.
- **Gain:** El campo `gain` se utiliza para multiplicar el valor leído. Por defecto, es `1` (sin alteración).

#### Ejemplo con decimales y hexadecimales:
```json
{
    "VOLTAGE_A": {
      "address": "8198",  // Dirección decimal = 0x2006
      "data_type": "f",
      "gain": "1"
    },
    "CURRENT_B": {
      "address": "0x200E",  // Dirección hexadecimal
      "data_type": "f",
      "gain": "1"
    }
}
```

---

## 🏗️ Estructura del Proyecto

```
gatewayEMS/
├── 📂 src/
│   ├── 📂 Config/          # Gestión de config.ini
│   │   └── config.py       # ConfigManager
│   ├── 📂 Core/            # Configuración base
│   │   ├── config.py       # Settings con Pydantic
│   │   └── watchdog.py     # Monitor de cambios
│   ├── 📂 Database/        # Capa de persistencia
│   │   ├── connection.py   # InfluxDB connection pool
│   │   ├── repository.py   # Data access layer
│   │   └── service.py      # Business logic
│   ├── 📂 Modbus/          # Comunicación Modbus
│   │   ├── app.py          # ModbusApp orchestrator
│   │   ├── client.py       # TCP/RTU clients
│   │   ├── modbusmap.py    # JSON map parser
│   │   ├── read.py         # Register reading
│   │   ├── util.py         # Helper functions
│   │   └── 📂 maps/        # JSON device maps
│   ├── 📂 Models/          # Domain models
│   │   └── model.py        # EnergyPoint, DeviceReadResult
│   ├── 📂 Task/            # Task orchestration
│   │   └── task.py         # TaskManager
│   └── 📂 Utils/           # Utilities
│       ├── logging.py      # Logger configuration
│       └── utils.py        # QueueManager
├── 📂 tests/               # Test suite (84% coverage)
│   ├── 📂 unit/            # Unit tests
│   ├── 📂 integration/     # Integration tests
│   └── 📂 fixtures/        # Test fixtures
├── 📂 scripts/             # Utility scripts
│   └── test_influxdb_manual.py
├── 📂 data/                # Configuration files
│   └── config.ini          # Main configuration
├── 📄 .env                 # Environment variables
├── 📄 docker-compose.yml   # Docker services
├── 📄 pyproject.toml       # Project metadata
└── 📄 README.md            # This file
```

---

## 🧪 Testing

El proyecto cuenta con **139 tests automatizados** con **84% de cobertura**:

```bash
# Ejecutar todos los tests con reporte de cobertura
uv run pytest

# Ver reporte HTML de cobertura
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html

# Ejecutar solo tests unitarios
uv run pytest tests/unit/ -v

# Ejecutar tests de integración
uv run pytest tests/integration/ -v

# Ejecutar tests con marcadores específicos
uv run pytest -m "unit" -v
```

### 📊 Cobertura por Módulo

| Módulo              | Cobertura | Tests |
|---------------------|-----------|-------|
| `Models/model.py`   | 98%       | 9     |
| `Modbus/read.py`    | 100%      | 16    |
| `Modbus/modbusmap.py` | 94%     | 8     |
| `Task/task.py`      | 88%       | 30    |
| `Config/config.py`  | 86%       | 15    |
| **Total**           | **84%**   | **139** |

---

## 📚 Documentación

### 📖 Guías Disponibles

- **[CONFIGURATION.md](docs/CONFIGURATION.md)** - Configuración detallada de dispositivos y mapas
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Explicación profunda de la arquitectura
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Guía para contribuidores
- **[API_REFERENCE.md](docs/API_REFERENCE.md)** - Referencia de APIs internas

### 🔧 Ejemplos de Uso

#### Ejemplo 1: Agregar un nuevo dispositivo Modbus TCP

```ini
[MAINMODBUS]
devicesnames = ExistingDevice, NewTCPMeter

[NewTCPMeter]
identify_device = 12345678-1234-1234-1234-123456789abc
devicetype = Energy_Meter
protocol = TCP
host = 192.168.1.100
port = 502
mapfile = src/Modbus/maps/NewTCPMeter.json
device_id = 1
modbusconnect = true
modbusread = true
```

#### Ejemplo 2: Crear un mapa Modbus personalizado

```json
{
  "VOLTAGE_L1": {
    "address": "0x0000",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT_L1": {
    "address": "0x0006",
    "data_type": "f",
    "gain": "0.001"
  },
  "POWER": {
    "address": "0x0010",
    "data_type": "I",
    "gain": "1"
  }
}
```

#### Ejemplo 3: Consultar datos en InfluxDB

```flux
from(bucket: "modbus_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "energy_data")
  |> filter(fn: (r) => r.device_id == "11")
  |> filter(fn: (r) => r._field == "voltage_a")
```

---

## 🐛 Troubleshooting

### Problema: InfluxDB no conecta

```bash
# Verificar que el contenedor está corriendo
docker ps | grep influxdb

# Ver logs de InfluxDB
docker logs gateway_ems_influxdb

# Reiniciar el contenedor
docker-compose restart influxdb
```

### Problema: Dispositivo Modbus no responde

1. Verificar conexión física (cable RS485/Ethernet)
2. Revisar configuración de baudrate y device_id
3. Verificar logs: `tail -f src/Log/gateway.log`
4. Probar con herramienta externa (modpoll, qmodmaster)

### Problema: Tests fallan

```bash
# Limpiar cache de pytest
rm -rf .pytest_cache __pycache__

# Reinstalar dependencias
uv sync --reinstall

# Ejecutar tests con verbose
uv run pytest -vv
```

---

## 🤝 Contribuciones

¡Las contribuciones son bienvenidas! Por favor sigue estos pasos:

1. **Fork** el repositorio
2. Crea una **rama** para tu feature (`git checkout -b feature/AmazingFeature`)
3. **Escribe tests** para tu código
4. Asegúrate de que **todos los tests pasan** (`uv run pytest`)
5. Haz **commit** de tus cambios (`git commit -m 'Add: AmazingFeature'`)
6. **Push** a la rama (`git push origin feature/AmazingFeature`)
7. Abre un **Pull Request**

### 📋 Checklist para PRs

- [ ] Tests agregados/actualizados
- [ ] Cobertura >= 80%
- [ ] Documentación actualizada
- [ ] Type hints agregados
- [ ] Logs apropiados
- [ ] Sin warnings de pytest

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Ver [LICENSE](LICENSE) para más detalles.

---

## 👥 Autores

- **Tu Nombre** - *Desarrollo inicial* - [@tu-usuario](https://github.com/tu-usuario)

---

## 🙏 Agradecimientos

- [PyModbus](https://github.com/pymodbus-dev/pymodbus) - Librería Modbus
- [InfluxDB](https://www.influxdata.com/) - Time series database
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager

---

## 📞 Soporte

¿Necesitas ayuda? Abre un [Issue](https://github.com/tu-usuario/gatewayEMS/issues) o contacta:

- 📧 Email: tu-email@example.com
- 💬 Discord: [Únete al servidor](https://discord.gg/tu-servidor)
- 📖 Wiki: [Documentation Wiki](https://github.com/tu-usuario/gatewayEMS/wiki)

---

<div align="center">

**⭐ Si este proyecto te ayudó, considera darle una estrella ⭐**

Made with ❤️ by [Tu Nombre]

[⬆ Volver arriba](#-gatewayems)

</div>
