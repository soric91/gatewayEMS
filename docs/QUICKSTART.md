# ⚡ Guía de Inicio Rápido - GatewayEMS

¿Primera vez con GatewayEMS? Esta guía te ayudará a tener el sistema funcionando en **menos de 10 minutos**.

---

## 📋 Requisitos Previos

Antes de empezar, asegúrate de tener:

- ✅ **Python 3.12+** instalado
- ✅ **Docker y Docker Compose** (para InfluxDB)
- ✅ **Git** (para clonar el repositorio)
- ✅ **uv** (o pip como alternativa)

---

## 🚀 5 Pasos para Empezar

### Paso 1: Clonar el Repositorio

```bash
git clone https://github.com/tu-usuario/gatewayEMS.git
cd gatewayEMS
```

---

### Paso 2: Instalar Dependencias

**Opción A: Con uv (Recomendado - Más rápido)**

```bash
# Instalar uv si no lo tienes
curl -LsSf https://astral.sh/uv/install.sh | sh

# Crear entorno virtual e instalar dependencias
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

uv sync --all-extras
```

**Opción B: Con pip (Alternativa)**

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -e ".[test]"
```

---

### Paso 3: Configurar InfluxDB

```bash
# Copiar archivo de variables de entorno
cp .env.example .env

# Generar token seguro (Linux/macOS)
openssl rand -base64 64 | tr -d "=+/" | cut -c1-64

# Editar .env con el token generado
nano .env
```

**Mínimo requerido en `.env`:**
```env
INFLUXDB_URL=http://localhost:8086
INFLUXDB_TOKEN=tu_token_generado_aqui_cambiar
INFLUXDB_ORG=gateway_ems
INFLUXDB_BUCKET=modbus_data
INFLUXDB_ADMIN_USER=admin
INFLUXDB_ADMIN_PASSWORD=tu_password_seguro
INFLUXDB_RETENTION=90
```

**Iniciar InfluxDB:**

```bash
# Iniciar contenedor Docker
docker-compose up -d

# Verificar que está corriendo
docker ps | grep influxdb
```

---

### Paso 4: Configurar Dispositivo Modbus

Edita `data/config.ini` con tu dispositivo:

```ini
[MAINMODBUS]
devicesnames = MiPrimerDispositivo
interval = 5
start_hour = 0
stop_hour = 23

[MiPrimerDispositivo]
identify_device = 11111111-2222-3333-4444-555555555555
devicetype = CT_Meter
protocol = RTU
serialport = /dev/ttyRS485
baudrate = 9600
mapfile = src/Modbus/maps/MiDispositivo.json
device_id = 11
modbusconnect = true
modbusread = true
```

**Para Modbus TCP:**
```ini
protocol = TCP
host = 192.168.1.100
port = 502
```

**Crear mapa JSON** en `src/Modbus/maps/MiDispositivo.json`:

```json
{
  "VOLTAGE": {
    "address": "0x0000",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT": {
    "address": "0x0002",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  }
}
```

---

### Paso 5: Ejecutar el Sistema

```bash
# Activar entorno virtual (si no está activado)
source .venv/bin/activate

# Iniciar GatewayEMS
python main.py
```

**Deberías ver:**

```
✅ TaskManager inicializado
🔌 Conectando MiPrimerDispositivo...
📖 Iniciando lectura de MiPrimerDispositivo...
📥 Procesando lote de resultados: 1/1 exitosos
✅ Lote procesado y guardado en InfluxDB
```

---

## 🎯 Verificar que Funciona

### 1. Ver Logs en Consola

Los emojis indican el estado:

- ✅ = Éxito
- 🔌 = Conectando
- 📖 = Leyendo
- ⚠️ = Advertencia
- ❌ = Error

### 2. Consultar InfluxDB

Abre tu navegador en: `http://localhost:8086`

**Login:**
- User: `admin` (o el que pusiste en `.env`)
- Password: tu contraseña de `.env`

**Ir a Data Explorer y ejecutar:**

```flux
from(bucket: "modbus_data")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "energy_data")
```

Deberías ver tus datos!

---

## 🧪 Ejecutar Tests (Opcional)

```bash
# Todos los tests
uv run pytest

# Solo tests unitarios
uv run pytest tests/unit/ -v

# Con reporte de cobertura
uv run pytest --cov=src --cov-report=html
open htmlcov/index.html
```

**Resultado esperado:**
```
========== 139 passed in 5.50s ==========
Coverage: 84%
```

---

## 🔧 Troubleshooting Rápido

### ❌ "InfluxDB connection failed"

```bash
# Verificar que Docker está corriendo
docker ps | grep influxdb

# Ver logs de InfluxDB
docker logs gateway_ems_influxdb

# Reiniciar contenedor
docker-compose restart influxdb
```

### ❌ "Serial port not found"

```bash
# Linux: Listar puertos
ls /dev/tty*

# Agregar permisos (Linux)
sudo usermod -a -G dialout $USER
# Logout y login de nuevo
```

### ❌ "Modbus timeout"

1. Verificar conexión física (cable RS485 o Ethernet)
2. Confirmar `device_id` correcto en config.ini
3. Probar con herramienta externa (modpoll, qmodmaster)

---

## 📚 Próximos Pasos

Ahora que tienes el sistema funcionando:

1. 📖 Lee la [Guía de Configuración](docs/CONFIGURATION.md) completa
2. 🏗️ Entiende la [Arquitectura](docs/ARCHITECTURE.md) del sistema
3. 🤝 Aprende a [Contribuir](CONTRIBUTING.md)
4. 🎨 Visualiza datos en Grafana (opcional)

---

## 💡 Tips Útiles

### Ejecutar en Background

```bash
# Con nohup
nohup python main.py > gateway.log 2>&1 &

# Ver logs en tiempo real
tail -f gateway.log

# Detener proceso
pkill -f main.py
```

### Systemd Service (Linux)

Crea `/etc/systemd/system/gatewayems.service`:

```ini
[Unit]
Description=GatewayEMS Service
After=network.target docker.service

[Service]
Type=simple
User=tu-usuario
WorkingDirectory=/ruta/a/gatewayEMS
ExecStart=/ruta/a/gatewayEMS/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Activar servicio
sudo systemctl daemon-reload
sudo systemctl enable gatewayems
sudo systemctl start gatewayems

# Ver estado
sudo systemctl status gatewayems
```

---

## 🆘 Ayuda

Si tienes problemas:

1. 📖 Revisa la [Documentación Completa](README.md)
2. 🐛 Abre un [Issue](https://github.com/tu-usuario/gatewayEMS/issues)
3. 💬 Únete a las [Discussions](https://github.com/tu-usuario/gatewayEMS/discussions)

---

<div align="center">

**¡Listo! Ya tienes GatewayEMS funcionando 🎉**

[⬆ Volver al README](README.md)

</div>
