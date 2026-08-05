# 📝 Guía de Configuración - GatewayEMS

Esta guía explica en detalle cómo configurar GatewayEMS para trabajar con tus dispositivos Modbus e InfluxDB.

---

## 📑 Tabla de Contenidos

- [Variables de Entorno (.env)](#-variables-de-entorno-env)
- [Configuración Principal (config.ini)](#-configuración-principal-configini)
- [Mapas Modbus (JSON)](#-mapas-modbus-json)
- [Tipos de Datos Modbus](#-tipos-de-datos-modbus)
- [Ejemplos Completos](#-ejemplos-completos)
- [Troubleshooting](#-troubleshooting)

---

## 🔐 Variables de Entorno (.env)

El archivo `.env` contiene credenciales sensibles y configuración de InfluxDB.

### Creación del archivo

```bash
# Copiar desde el ejemplo
cp .env.example .env

# Editar con tu editor favorito
nano .env
```

### Variables Requeridas

```env
# ===================================
# InfluxDB Configuration
# ===================================

# URL de conexión
# Para Docker: http://influxdb:8086
# Para local: http://localhost:8086
INFLUXDB_URL=http://localhost:8086

# Token de autenticación (generado automáticamente)
# Debe tener permisos de lectura/escritura en el bucket
INFLUXDB_TOKEN=tu_token_super_secreto_de_64_caracteres_minimo_aqui

# Usuario administrador
INFLUXDB_ADMIN_USER=admin

# Contraseña del administrador
INFLUXDB_ADMIN_PASSWORD=tu_password_seguro_aqui

# Organización (namespace para buckets)
INFLUXDB_ORG=gateway_ems

# Bucket para almacenar datos Modbus
INFLUXDB_BUCKET=modbus_data

# Retención de datos en días
# Ejemplos: 7, 30, 90, 365
INFLUXDB_RETENTION=90
```

### 🔑 Generación de Token Seguro

```bash
# Opción 1: Usar OpenSSL
openssl rand -base64 64 | tr -d "=+/" | cut -c1-64

# Opción 2: Usar Python
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Opción 3: Script incluido
./scripts/generate_influxdb_token.sh
```

### ⚠️ Seguridad

- ❌ **NUNCA** commitees el archivo `.env` a Git
- ✅ Asegúrate de que `.env` está en `.gitignore`
- ✅ Usa contraseñas fuertes (mínimo 16 caracteres)
- ✅ Rota los tokens periódicamente en producción

---

## ⚙️ Configuración Principal (config.ini)

El archivo `data/config.ini` controla el comportamiento del sistema y los dispositivos Modbus.

### Estructura General

```ini
[MAINMODBUS]
# Configuración global del sistema

[DEVICE_NAME_1]
# Configuración del primer dispositivo

[DEVICE_NAME_2]
# Configuración del segundo dispositivo
```

---

## 📊 Sección [MAINMODBUS]

Controla el comportamiento global del sistema.

### Parámetros

```ini
[MAINMODBUS]
# Lista de dispositivos a gestionar (separados por comas)
devicesnames = Modbus_DTSU666, Energy_Meter_2, Inverter_1

# Intervalo de lectura en segundos
interval = 5

# Hora de inicio de lecturas (0-23)
start_hour = 0

# Hora de finalización de lecturas (0-23)
stop_hour = 23
```

| Parámetro      | Tipo   | Requerido | Descripción                                    | Ejemplo          |
|----------------|--------|-----------|------------------------------------------------|------------------|
| `devicesnames` | string | ✅ Sí     | Lista de dispositivos (separados por comas)    | `Device1, Dev2`  |
| `interval`     | int    | ✅ Sí     | Segundos entre lecturas                        | `5`              |
| `start_hour`   | int    | ❌ No     | Hora de inicio (default: 0)                    | `8`              |
| `stop_hour`    | int    | ❌ No     | Hora de fin (default: 23)                      | `18`             |

### 🕐 Control de Horarios

Puedes limitar las lecturas a horarios específicos:

```ini
[MAINMODBUS]
devicesnames = MeterA
interval = 10
start_hour = 8   # Iniciar a las 08:00
stop_hour = 18   # Detener a las 18:59
```

**Comportamiento:**
- ✅ De 08:00 a 18:59 → Lee cada 10 segundos
- ⏸️ De 19:00 a 07:59 → No realiza lecturas (ahorra recursos)

---

## 🔌 Sección [DEVICE_NAME]

Cada dispositivo listado en `devicesnames` debe tener su propia sección.

### Parámetros Comunes

```ini
[Modbus_DTSU666]
# UUID único del dispositivo (para tracking)
identify_device = bf6a469f-4c2a-4402-9438-49a491ad2238

# Tipo de dispositivo (libre, para tu referencia)
devicetype = CT_Meter

# ID Modbus del esclavo (slave address)
device_id = 11

# Archivo JSON con el mapa de registros
mapfile = src/Modbus/maps/Modbus_DTSU666.json

# Control de conexión
modbusconnect = true

# Control de lectura
modbusread = true

# Protocolo: RTU o TCP
protocol = RTU
```

| Parámetro         | Tipo    | Requerido | Descripción                              | Ejemplo                                   |
|-------------------|---------|-----------|------------------------------------------|-------------------------------------------|
| `identify_device` | UUID    | ✅ Sí     | Identificador único del dispositivo      | `bf6a469f-4c2a-4402-9438-49a491ad2238`    |
| `devicetype`      | string  | ✅ Sí     | Tipo de dispositivo                      | `CT_Meter`, `Inverter`, `Battery`         |
| `device_id`       | int     | ✅ Sí     | Slave address Modbus (1-255)             | `11`                                      |
| `mapfile`         | path    | ✅ Sí     | Ruta al archivo JSON de registros        | `src/Modbus/maps/device.json`             |
| `modbusconnect`   | boolean | ✅ Sí     | Conectar al dispositivo                  | `true`                                    |
| `modbusread`      | boolean | ✅ Sí     | Leer datos del dispositivo               | `true`                                    |
| `protocol`        | enum    | ✅ Sí     | Protocolo: `RTU` o `TCP`                 | `RTU`                                     |

---

## 📡 Configuración Modbus RTU

Para dispositivos conectados por serial (RS485/RS232).

```ini
[Device_RTU]
identify_device = 12345678-1234-1234-1234-123456789abc
devicetype = Energy_Meter
protocol = RTU
device_id = 1
mapfile = src/Modbus/maps/EnergyMeter.json
modbusconnect = true
modbusread = true

# Parámetros específicos RTU
serialport = /dev/ttyRS485
baudrate = 9600
parity = N
stopbits = 1
bytesize = 8
```

### Parámetros RTU

| Parámetro    | Tipo   | Requerido | Valores Posibles           | Default | Descripción                |
|--------------|--------|-----------|----------------------------|---------|----------------------------|
| `serialport` | string | ✅ Sí     | `/dev/ttyUSB0`, COM1, etc. | -       | Puerto serial del sistema  |
| `baudrate`   | int    | ✅ Sí     | 9600, 19200, 38400, 115200 | -       | Velocidad de comunicación  |
| `parity`     | char   | ❌ No     | `N`, `E`, `O`              | `N`     | Bit de paridad             |
| `stopbits`   | int    | ❌ No     | `1`, `2`                   | `1`     | Bits de parada             |
| `bytesize`   | int    | ❌ No     | `7`, `8`                   | `8`     | Tamaño del byte            |

### 🔍 Encontrar tu puerto serial

**Linux:**
```bash
# Listar puertos disponibles
ls -la /dev/tty*

# Puertos USB comunes
ls /dev/ttyUSB*
ls /dev/ttyRS485*

# Ver información detallada
dmesg | grep tty
```

**Windows:**
```powershell
# Device Manager → Ports (COM & LPT)
# O usar PowerShell:
Get-WmiObject Win32_SerialPort | Select Name, DeviceID
```

---

## 🌐 Configuración Modbus TCP

Para dispositivos conectados por Ethernet.

```ini
[Device_TCP]
identify_device = 87654321-4321-4321-4321-987654321cba
devicetype = Inverter
protocol = TCP
device_id = 1
mapfile = src/Modbus/maps/Inverter.json
modbusconnect = true
modbusread = true

# Parámetros específicos TCP
host = 192.168.1.100
port = 502
```

### Parámetros TCP

| Parámetro | Tipo   | Requerido | Descripción                    | Default | Ejemplo          |
|-----------|--------|-----------|--------------------------------|---------|------------------|
| `host`    | string | ✅ Sí     | IP o hostname del dispositivo  | -       | `192.168.1.100`  |
| `port`    | int    | ❌ No     | Puerto Modbus TCP              | `502`   | `502`            |

### 🔍 Verificar conectividad TCP

```bash
# Ping al dispositivo
ping 192.168.1.100

# Verificar puerto abierto
nc -zv 192.168.1.100 502

# O con nmap
nmap -p 502 192.168.1.100
```

---

## 📋 Mapas Modbus (JSON)

Los mapas definen qué registros Modbus leer y cómo interpretarlos.

### Estructura del Mapa

```json
{
  "VARIABLE_NAME": {
    "address": "dirección_del_registro",
    "data_type": "tipo_de_dato",
    "gain": "factor_de_escala",
    "function_code": 3
  }
}
```

### Ejemplo Completo

```json
{
  "VOLTAGE_A": {
    "address": "8198",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT_A": {
    "address": "8206",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "POWER_TOTAL": {
    "address": "0x2100",
    "data_type": "I",
    "gain": "0.001",
    "function_code": 3
  },
  "TEMPERATURE": {
    "address": "100",
    "data_type": "h",
    "gain": "0.1",
    "function_code": 4
  }
}
```

### Campos del Mapa

| Campo           | Tipo   | Requerido | Descripción                          | Ejemplo      |
|-----------------|--------|-----------|--------------------------------------|--------------|
| `address`       | string | ✅ Sí     | Dirección decimal o hex (con `0x`)   | `"8198"` o `"0x2006"` |
| `data_type`     | string | ✅ Sí     | Tipo de dato Modbus (ver tabla)      | `"f"`        |
| `gain`          | string | ✅ Sí     | Factor de multiplicación             | `"1"`, `"0.001"` |
| `function_code` | int    | ❌ No     | Función Modbus (3 o 4)               | `3`          |

---

## 📊 Tipos de Datos Modbus

GatewayEMS soporta los siguientes tipos de datos según el estándar Modbus:

| Tipo     | Código | Registros | Rango                        | Descripción                    |
|----------|--------|-----------|------------------------------|--------------------------------|
| `FLOAT`  | `f`    | 2         | ±3.4E+38                     | Float 32 bits (IEEE 754)       |
| `INT16`  | `h`    | 1         | -32,768 a 32,767             | Entero con signo 16 bits       |
| `UINT16` | `H`    | 1         | 0 a 65,535                   | Entero sin signo 16 bits       |
| `INT32`  | `i`    | 2         | -2,147,483,648 a 2,147,483,647 | Entero con signo 32 bits     |
| `UINT32` | `I`    | 2         | 0 a 4,294,967,295            | Entero sin signo 32 bits       |

### 🔢 Formato de Direcciones

Puedes especificar direcciones en **decimal** o **hexadecimal**:

```json
{
  "VOLTAGE": {
    "address": "8198",      // ✅ Decimal
    "data_type": "f",
    "gain": "1"
  },
  "CURRENT": {
    "address": "0x200E",    // ✅ Hexadecimal (con prefijo 0x)
    "data_type": "f",
    "gain": "1"
  }
}
```

### ⚖️ Factor de Escala (Gain)

El `gain` multiplica el valor leído. Útil para conversiones:

```json
{
  "POWER_WATTS": {
    "address": "100",
    "data_type": "I",
    "gain": "1"           // Valor directo: 1000W → 1000.0
  },
  "POWER_KILOWATTS": {
    "address": "100",
    "data_type": "I",
    "gain": "0.001"       // Convertir a kW: 1000W → 1.0kW
  },
  "TEMPERATURE_C": {
    "address": "200",
    "data_type": "h",
    "gain": "0.1"         // Temp en décimas: 235 → 23.5°C
  }
}
```

### 📖 Function Codes

| Code | Nombre                   | Descripción                        | Uso Común                |
|------|--------------------------|------------------------------------|--------------------------|
| `3`  | Read Holding Registers   | Lee registros de lectura/escritura | Valores configurables    |
| `4`  | Read Input Registers     | Lee registros de solo lectura      | Valores medidos/sensores |

```json
{
  "SETPOINT": {
    "address": "1000",
    "data_type": "f",
    "gain": "1",
    "function_code": 3    // Holding register (configurable)
  },
  "SENSOR_VALUE": {
    "address": "2000",
    "data_type": "f",
    "gain": "1",
    "function_code": 4    // Input register (solo lectura)
  }
}
```

---

## 🎯 Ejemplos Completos

### Ejemplo 1: Medidor de Energía CT (RTU)

**config.ini:**
```ini
[MAINMODBUS]
devicesnames = CT_Meter_Main
interval = 5
start_hour = 0
stop_hour = 23

[CT_Meter_Main]
identify_device = a1b2c3d4-e5f6-7890-abcd-ef1234567890
devicetype = CT_Meter
protocol = RTU
serialport = /dev/ttyRS485
baudrate = 9600
mapfile = src/Modbus/maps/CT_Meter.json
device_id = 11
modbusconnect = true
modbusread = true
```

**src/Modbus/maps/CT_Meter.json:**
```json
{
  "VOLTAGE_A": {
    "address": "8198",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "VOLTAGE_B": {
    "address": "8200",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "VOLTAGE_C": {
    "address": "8202",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT_A": {
    "address": "8206",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT_B": {
    "address": "8208",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "CURRENT_C": {
    "address": "8210",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "POWER_TOTAL": {
    "address": "8220",
    "data_type": "f",
    "gain": "1",
    "function_code": 3
  },
  "ENERGY_TOTAL": {
    "address": "8240",
    "data_type": "I",
    "gain": "0.01",
    "function_code": 3
  }
}
```

---

### Ejemplo 2: Inversor Solar (TCP)

**config.ini:**
```ini
[MAINMODBUS]
devicesnames = Solar_Inverter_1
interval = 10
start_hour = 6
stop_hour = 20

[Solar_Inverter_1]
identify_device = 11111111-2222-3333-4444-555555555555
devicetype = Solar_Inverter
protocol = TCP
host = 192.168.1.50
port = 502
mapfile = src/Modbus/maps/SolarInverter.json
device_id = 1
modbusconnect = true
modbusread = true
```

**src/Modbus/maps/SolarInverter.json:**
```json
{
  "PV_VOLTAGE_1": {
    "address": "0x0006",
    "data_type": "H",
    "gain": "0.1",
    "function_code": 4
  },
  "PV_CURRENT_1": {
    "address": "0x0007",
    "data_type": "H",
    "gain": "0.01",
    "function_code": 4
  },
  "PV_POWER": {
    "address": "0x000A",
    "data_type": "I",
    "gain": "1",
    "function_code": 4
  },
  "AC_VOLTAGE": {
    "address": "0x0014",
    "data_type": "H",
    "gain": "0.1",
    "function_code": 4
  },
  "AC_POWER": {
    "address": "0x0016",
    "data_type": "I",
    "gain": "1",
    "function_code": 4
  },
  "DAILY_ENERGY": {
    "address": "0x0020",
    "data_type": "I",
    "gain": "0.01",
    "function_code": 4
  },
  "TOTAL_ENERGY": {
    "address": "0x0022",
    "data_type": "I",
    "gain": "0.1",
    "function_code": 4
  },
  "INVERTER_TEMP": {
    "address": "0x0030",
    "data_type": "h",
    "gain": "0.1",
    "function_code": 4
  }
}
```

---

### Ejemplo 3: Múltiples Dispositivos

```ini
[MAINMODBUS]
devicesnames = Meter_Grid, Meter_Solar, Battery_Monitor
interval = 5

[Meter_Grid]
identify_device = grid-meter-001
devicetype = Grid_Meter
protocol = RTU
serialport = /dev/ttyRS485-1
baudrate = 9600
device_id = 1
mapfile = src/Modbus/maps/GridMeter.json
modbusconnect = true
modbusread = true

[Meter_Solar]
identify_device = solar-meter-002
devicetype = Solar_Meter
protocol = TCP
host = 192.168.1.101
port = 502
device_id = 1
mapfile = src/Modbus/maps/SolarMeter.json
modbusconnect = true
modbusread = true

[Battery_Monitor]
identify_device = battery-bms-003
devicetype = Battery_BMS
protocol = TCP
host = 192.168.1.102
port = 502
device_id = 1
mapfile = src/Modbus/maps/BatteryBMS.json
modbusconnect = true
modbusread = true
```

---

## 🔧 Troubleshooting

### ❌ Error: "Device not found in config"

**Causa:** El dispositivo está en `devicesnames` pero no tiene su sección.

**Solución:**
```ini
[MAINMODBUS]
devicesnames = MyDevice    # ← Listado aquí

[MyDevice]                 # ← Falta esta sección
# ... configuración ...
```

---

### ❌ Error: "Failed to connect to serial port"

**Causa:** Puerto serial incorrecto o sin permisos.

**Solución Linux:**
```bash
# Verificar permisos
ls -la /dev/ttyRS485

# Agregar usuario al grupo dialout
sudo usermod -a -G dialout $USER

# Logout y login de nuevo
```

**Solución Windows:**
- Verificar en Device Manager que el puerto existe
- Instalar drivers del adaptador USB-RS485

---

### ❌ Error: "Modbus slave did not respond"

**Posibles causas:**
1. `device_id` incorrecto
2. Baudrate incorrecto (RTU)
3. Dispositivo apagado o desconectado
4. Cable mal conectado

**Solución:**
1. Verificar con herramienta externa (modpoll, qmodmaster)
2. Revisar manual del dispositivo para confirmar slave address
3. Probar diferentes baudrates (9600, 19200, 38400)

---

### ❌ Error: "Address out of range"

**Causa:** Dirección Modbus inválida en el mapa JSON.

**Solución:**
- Consultar manual del dispositivo para direcciones válidas
- Verificar que las direcciones estén en el rango del dispositivo
- Algunos dispositivos usan offset (ej: dirección 40001 = address 0)

---

### ❌ Warning: "Data type mismatch"

**Causa:** El tipo de dato no coincide con lo que retorna el dispositivo.

**Solución:**
- Verificar en el manual si el registro es float, int16, int32, etc.
- Probar con diferentes tipos de datos para encontrar el correcto

---

## 📚 Referencias

- [Especificación Modbus](https://www.modbus.org/specs.php)
- [PyModbus Documentation](https://pymodbus.readthedocs.io/)
- [InfluxDB Documentation](https://docs.influxdata.com/)

---

## 🆘 Ayuda Adicional

Si tienes problemas con la configuración:

1. 📖 Revisa los logs en `src/Log/gateway.log`
2. 🧪 Ejecuta los tests: `uv run pytest -v`
3. 🐛 Abre un issue en GitHub con:
   - Tu `config.ini` (sin datos sensibles)
   - Logs relevantes
   - Descripción del problema

---

[⬆ Volver al README principal](../README.md)
