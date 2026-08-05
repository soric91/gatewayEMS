# Gateway EMS — Diagramas de Arquitectura y Escalabilidad

Generado a partir del análisis completo de `src/` (21 archivos, ~2.2k LOC).

---

## 1. Arquitectura completa (estado actual)

```mermaid
flowchart TB
    subgraph ENTRY["Entrypoint"]
        MAIN["main.py<br/>asyncio.run(main)"]
    end

    subgraph CONFIG["Capa Configuración"]
        CFGMGR["ConfigManager<br/>src/Config/config.py<br/>configparser + reload()"]
        INI[("config.ini<br/>MAINMODBUS + DEVICE_*")]
        SETTINGS["Settings (pydantic)<br/>src/Core/config.py"]
        ENV[(".env / .env.local")]
        LOG["get_logger()<br/>src/Utils/logging.py<br/>RotatingFileHandler"]
    end

    subgraph ORCH["Capa Orquestación"]
        WD["BaseWatchdog<br/>src/Core/watchdog.py<br/>poll 2.0s"]
        TM["TaskManager<br/>src/Task/task.py<br/>extends BaseWatchdog"]
        QM["QueueManager<br/>asyncio.Queue"]
    end

    subgraph TASKS["Tareas asyncio"]
        T1["task_read_modbus_periodic<br/>loop cada interval/2"]
        T2["task_process_queue<br/>consume → InfluxDB"]
        T3["task_publish_mqtt<br/>consume → MQTT"]
    end

    subgraph MODBUS["Capa Modbus"]
        APP["ModbusApp<br/>src/Modbus/app.py<br/>orquestador"]
        FACT["ModbusClientFactory<br/>src/Modbus/client.py<br/>agrupa por puerto/IP"]
        MAP["ModbusDeviceMap<br/>src/Modbus/modbusmap.py"]
        UTIL["util.py<br/>group_addresses_device<br/>create_individual_blocks<br/>ModbusRegister/BlockRead"]
        READ["read_registers()<br/>src/Modbus/read.py<br/>gather por slave"]
        JSON[("maps/*.json<br/>address/data_type/gain")]
    end

    subgraph MODELS["Modelos"]
        DRR["DeviceReadResult"]
        EP["EnergyPoint<br/>to_influx_point()"]
        ENUMS["NameParamsModbus<br/>ProtocolCom / DATATYPE"]
    end

    subgraph PERSIST["Capa Persistencia"]
        SVC["ModbusService<br/>Database/service.py"]
        REPO["InfluxDBRepository<br/>Database/repository.py"]
        CONN["InfluxDBConnection<br/>retry x3 backoff x2"]
    end

    subgraph EXT["Sistemas Externos"]
        HW1["Dispositivos RTU<br/>/dev/ttyRS485"]
        HW2["Dispositivos TCP<br/>host:port"]
        IDB[("InfluxDB 2.7<br/>bucket modbus_data")]
        BROKER["Broker MQTT<br/>aiomqtt"]
    end

    MAIN --> CFGMGR
    MAIN --> TM
    INI --> CFGMGR
    ENV --> SETTINGS
    CFGMGR --> LOG

    TM -.hereda.-> WD
    WD -->|reload + diff| CFGMGR
    WD -->|on_config_changed| TM
    TM --> APP
    TM --> QM
    TM --> SVC
    TM --> MQTTM["MQTTManager<br/>src/Utils/utils.py"]

    TM --> T1 & T2 & T3
    T1 -->|read_all| APP
    T1 -->|publish| QM
    QM --> T2
    QM --> T3
    T2 --> SVC
    T3 --> MQTTM

    APP --> FACT
    APP --> MAP
    APP --> READ
    MAP --> UTIL
    JSON --> MAP
    FACT --> HW1
    FACT --> HW2
    READ --> HW1
    READ --> HW2
    APP --> DRR

    SVC --> EP
    DRR --> EP
    EP --> REPO
    REPO --> CONN
    CONN --> IDB
    SETTINGS --> CONN
    SETTINGS --> MQTTM
    MQTTM --> BROKER

    ENUMS -.usado por.-> APP
    ENUMS -.usado por.-> FACT
    ENUMS -.usado por.-> MAP

    classDef ext fill:#2d3748,stroke:#63b3ed,color:#fff
    classDef task fill:#22543d,stroke:#68d391,color:#fff
    class HW1,HW2,IDB,BROKER ext
    class T1,T2,T3 task
```

---

## 2. Diagrama de clases

```mermaid
classDiagram
    class ConfigManager {
        +str config_file
        +ConfigParser config
        +Path config_path
        +reload()
        +get_value(section, key, fallback)
        +get_section_dict(section) dict
        +add_device_section(name, data) bool
        +remove_device_section(name) bool
        +set_device_value(name, key, value) bool
        +device_exists(name) bool
    }

    class BaseWatchdog {
        +ConfigManager config
        +str connect
        +str readstart
        +float poll_interval
        +dict prev_values
        +start()
        +stop()
        -_monitor_loop()
        -_check_and_notify()
        +on_config_changed(dev, connect, read)*
        -_get_devices() list
    }

    class TaskManager {
        +MQTTManager mqtt_manager
        +ModbusService modbus_service
        +ModbusApp modbus_app
        +QueueManager queue_manager
        +Set _connected_devices
        +Set _reading_devices
        +Lock _read_lock
        +int interval, start_hour, stop_hour
        +initialize() bool
        +on_config_changed(...)
        +task_read_modbus_periodic()
        +task_process_queue()
        +task_publish_mqtt()
        +start_all_tasks()
        +stop_all_tasks()
        -_is_active_hour() bool
    }

    class ModbusApp {
        +dict clients
        +dict~str,ModbusDeviceMap~ device_maps
        +dict device_configs
        +initialize() bool
        -_load_configs() bool
        -_load_maps() bool
        +connect_device(name) bool
        +disconnect_device(name)
        +read_all() List~DeviceReadResult~
        +shutdown()
    }

    class ModbusClientFactory {
        +dict config_dict
        +dict clients
        +Set failed_clients
        +float connection_timeout
        +start_connection() dict
        -_get_client_key(cfg, proto) str
        -_create_and_connect_client(...) Client
        -_build_device_info(...) dict
        +close_all_connections()
    }

    class ModbusDeviceMap {
        +str device_name
        +str map_file_path
        +int max_gap
        +bool block_reading
        +load_map() bool
        +build_read_blocks() list
        +get_read_params() tuple
        +parse_raw_data(regs) dict
        +get_variables_list() list
    }

    class ModbusBlockRead {
        +int start_address
        +int count
        +List~ModbusRegister~ registers
        +parse_all(raw) dict
    }

    class ModbusRegister {
        +str name
        +int address
        +DATATYPE data_type
        +float gain
        +int offset
        +parse_value(raw) Any
    }

    class DeviceReadResult {
        +str device_name
        +str device_id
        +str identify_device
        +str timestamp
        +dict data
        +bool success
        +str device_type
        +str error
    }

    class EnergyPoint {
        +str device_name, device_id
        +str device_type, identify_device
        +str timestamp
        +dict measurements
        +str measurement_name
        +from_device_read_result(r)$ EnergyPoint
        +batch_from_results(rs)$ List
        +to_influx_point() Point
        -_normalize_fields(d) dict
    }

    class ModbusService {
        +InfluxDBRepository _repository
        +initialize()
        +save_batch(results)
        +shutdown()
    }

    class InfluxDBRepository {
        +InfluxDBConnection _connection
        +write_api _write_api
        +initialize()
        +save_points(points)
        +shutdown()
    }

    class InfluxDBConnection {
        +str org, bucket, _url, _token
        +int _max_retries, _retry_delay, _retry_backoff
        +connect() bool
        -_health_check() bool
        +disconnect()
        +ensure_connected() bool
    }

    class QueueManager {
        +asyncio.Queue queue
        +publish(data)
        +consume()
    }

    class MQTTManager {
        +aiomqtt.Client _client
        +connect()
        +disconnect()
        +publish(payload)
        -_reconnect()
    }

    BaseWatchdog <|-- TaskManager
    BaseWatchdog o-- ConfigManager
    TaskManager o-- ModbusApp
    TaskManager o-- QueueManager
    TaskManager o-- MQTTManager
    TaskManager o-- ModbusService
    ModbusApp o-- ConfigManager
    ModbusApp ..> ModbusClientFactory : crea
    ModbusApp o-- ModbusDeviceMap
    ModbusApp ..> DeviceReadResult : produce
    ModbusDeviceMap o-- ModbusBlockRead
    ModbusBlockRead o-- ModbusRegister
    ModbusService o-- InfluxDBRepository
    InfluxDBRepository o-- InfluxDBConnection
    ModbusService ..> EnergyPoint : transforma
    EnergyPoint ..> DeviceReadResult : from
```

---

## 3. Secuencia — ciclo de vida completo

```mermaid
sequenceDiagram
    autonumber
    participant M as main.py
    participant TM as TaskManager
    participant WD as BaseWatchdog
    participant CFG as config.ini
    participant APP as ModbusApp
    participant F as ClientFactory
    participant HW as Dispositivo Modbus
    participant Q as QueueManager
    participant SVC as ModbusService
    participant IDB as InfluxDB
    participant MQ as MQTT Broker

    M->>TM: TaskManager(ConfigManager())
    TM->>TM: __post_init__ (interval, horario)
    M->>TM: initialize()
    TM->>MQ: MQTTManager.connect()
    TM->>APP: ModbusApp(config)
    TM->>SVC: ModbusService.initialize()
    SVC->>IDB: connect() retry x3 backoff x2
    TM->>APP: _load_configs() + _load_maps()
    APP->>APP: ModbusDeviceMap.load_map()<br/>build_read_blocks()
    TM->>WD: start() → _check_and_notify + _monitor_loop

    rect rgb(30,50,70)
    note over WD,CFG: Activación por config (hot-reload cada 2s)
    WD->>CFG: reload() + getboolean(modbusconnect/modbusread)
    CFG-->>WD: (True, True) ≠ prev
    WD->>TM: on_config_changed(dev, True, True)
    TM->>APP: connect_device(dev)
    APP->>F: start_connection(factory_config)
    F->>HW: AsyncModbusSerial/Tcp connect()
    HW-->>F: connected
    F-->>APP: {client_key: {client, devices[]}}
    TM->>TM: _connected_devices.add + _reading_devices.add
    end

    M->>TM: start_all_tasks()

    loop cada interval/2 s, si _is_active_hour()
        TM->>APP: read_all()
        APP->>HW: read_registers(slaves, addrs, counts)
        HW-->>APP: registros crudos
        APP->>APP: parse_raw_data → DeviceReadResult[]
        APP-->>TM: results
        TM->>Q: publish({results, success_count, total_count})
    end

    par Consumidor A
        Q-->>TM: consume() → task_process_queue
        TM->>SVC: save_batch(results)
        SVC->>SVC: EnergyPoint.batch_from_results<br/>to_influx_point()
        SVC->>IDB: write(points)
    and Consumidor B
        Q-->>TM: consume() → task_publish_mqtt
        TM->>MQ: publish(result) por cada lectura
    end

    M->>TM: stop_all_tasks()
    TM->>WD: stop()
    TM->>SVC: shutdown()
    TM->>APP: shutdown() → cierra clientes
```

---

## 4. Máquina de estados por dispositivo (watchdog)

Controlada por `modbusconnect` / `modbusread` en `config.ini`.

```mermaid
stateDiagram-v2
    [*] --> IDLE : arranque

    IDLE --> CONNECTED : connect=T, read=F<br/>connect_device()
    IDLE --> READING : connect=T, read=T<br/>connect + add a _reading_devices
    IDLE --> IDLE : connect=F, read=T<br/>⚠️ fuerza modbusread=False

    CONNECTED --> READING : read=T<br/>_reading_devices.add
    CONNECTED --> IDLE : connect=F<br/>disconnect_device()

    READING --> CONNECTED : read=F<br/>_reading_devices.remove + espera _read_lock
    READING --> IDLE : connect=F, read=F<br/>remove + disconnect bajo lock

    note right of READING
        Solo dispositivos en _reading_devices
        pasan el filtro de read_all()
    end note

    note left of IDLE
        Combinación inválida (F,T)
        se auto-corrige escribiendo
        modbusread=False en config.ini
    end note
```

---

## 5. Puntos de extensión — cómo escala con nuevas funciones

```mermaid
flowchart LR
    subgraph CORE["Núcleo estable (no tocar)"]
        direction TB
        TMC["TaskManager<br/>+ BaseWatchdog"]
        QC["QueueManager"]
        DRRC["DeviceReadResult"]
    end

    subgraph P1["① Nuevo protocolo de campo"]
        DNP["DNP3 / IEC-104 / SunSpec / BACnet"]
        NOTE1["Añadir en ProtocolCom<br/>+ rama en _create_and_connect_client<br/>+ nuevo read_*.py"]
    end

    subgraph P2["② Nuevo tipo de dispositivo"]
        DEV["Inverter / Battery / Meter"]
        NOTE2["Solo JSON en maps/<br/>+ sección en config.ini<br/>0 líneas de código"]
    end

    subgraph P3["③ Nuevo sink de datos"]
        SINK["TimescaleDB / Kafka / REST / S3"]
        NOTE3["Nueva clase estilo InfluxDBRepository<br/>+ task_XXX consumidora"]
    end

    subgraph P4["④ Nuevo tipo de dato"]
        DT["INT64 / STRING / BITFIELD / BCD"]
        NOTE4["DATATYPE enum<br/>+ get_register_count<br/>+ ModbusRegister.parse_value"]
    end

    subgraph P5["⑤ Nueva estrategia de lectura"]
        RS["block / individual / adaptativa / por prioridad"]
        NOTE5["util.py: nueva función create_*_blocks<br/>+ flag en config.ini"]
    end

    subgraph P6["⑥ Nueva fuente de control"]
        CTL["API REST / MQTT command / Web UI"]
        NOTE6["ConfigManager.set_device_value()<br/>watchdog lo detecta en ≤2s"]
    end

    subgraph P7["⑦ Nueva tarea periódica"]
        TSK["health metrics / OTA / alarmas / agregados"]
        NOTE7["async def task_XXX<br/>+ entrada en start_all_tasks"]
    end

    P1 --> FACTX["ModbusClientFactory"] --> CORE
    P2 --> MAPX["ModbusDeviceMap"] --> CORE
    P4 --> UTILX["util.ModbusRegister"] --> MAPX
    P5 --> UTILX
    CORE --> P3
    P6 --> CFGX["config.ini"] --> CORE
    CORE --> P7

    classDef ext fill:#1a365d,stroke:#4299e1,color:#fff
    classDef note fill:#2d3748,stroke:#718096,color:#cbd5e0,font-size:11px
    class DNP,DEV,SINK,DT,RS,CTL,TSK ext
    class NOTE1,NOTE2,NOTE3,NOTE4,NOTE5,NOTE6,NOTE7 note
```

### Coste de cada extensión

| # | Extensión | Archivos a tocar | Código nuevo |
|---|-----------|------------------|--------------|
| ② | Nuevo dispositivo del mismo protocolo | `maps/*.json`, `config.ini` | **0 LOC** |
| ⑤ | Estrategia de lectura | `Modbus/util.py`, `modbusmap.py` | ~40 LOC |
| ④ | Tipo de dato | `Models/model.py`, `Modbus/util.py` | ~15 LOC |
| ⑦ | Tarea periódica | `Task/task.py` | ~30 LOC |
| ③ | Sink de datos | `Database/` (nuevo repo+service) | ~120 LOC |
| ⑥ | Fuente de control externa | módulo nuevo + `Config/config.py` | ~150 LOC |
| ① | Protocolo de campo | `Modbus/client.py`, `read.py`, `model.py` | ~250 LOC |

---

## 6. Escalabilidad de conexiones (agrupación por bus)

`ModbusClientFactory` agrupa por `serialport` (RTU) o `host` (TCP). N dispositivos con el mismo bus ⇒ 1 cliente.

```mermaid
flowchart TB
    subgraph CFG["config.ini — devicesnames"]
        D1["Modbus_DTSU666<br/>device_id = 11,12,13<br/>RTU /dev/ttyRS485"]
        D2["Inverter_X<br/>device_id = 1,2<br/>TCP 192.168.1.50"]
        D3["Meter_Y<br/>device_id = 5<br/>RTU /dev/ttyRS485"]
    end

    subgraph CLIENTS["ModbusApp.clients (dict por client_key)"]
        C1["'/dev/ttyRS485'<br/>AsyncModbusSerialClient<br/>devices: [DTSU_11, DTSU_12, DTSU_13, Meter_Y_5]"]
        C2["'192.168.1.50'<br/>AsyncModbusTcpClient<br/>devices: [Inv_1, Inv_2]"]
    end

    subgraph READ["read_all() → por client → por device_map"]
        R1["gather() por slave<br/>gather() por bloque"]
    end

    D1 --> C1
    D3 --> C1
    D2 --> C2
    C1 --> R1
    C2 --> R1
    R1 --> RES["List[DeviceReadResult]<br/>1 por (device_name, device_id)"]

    note1["⚠️ RTU es half-duplex:<br/>gather sobre el mismo puerto serie<br/>NO da paralelismo real"]
    C1 -.-> note1

    classDef warn fill:#742a2a,stroke:#fc8181,color:#fff
    class note1 warn
```

---

## 7. Despliegue

```mermaid
flowchart TB
    subgraph HOST["Host / Gateway edge"]
        subgraph PY["Proceso Python 3.12 (uv)"]
            APP2["gatewayEMS<br/>main.py"]
        end
        subgraph DOCKER["docker-compose"]
            IDB2[("influxdb:2.7<br/>:8086<br/>cpus 1.5 / mem 1G<br/>retention 90d")]
        end
        VOL[("/mnt/disco/influxdb/{data,config,backups}")]
        LOGF[("src/Log/gateway_ems.log<br/>rotating 1.4MB x5")]
        SER["/dev/ttyRS485"]
    end

    BR["Broker MQTT externo"]
    HWX["Medidores / Inversores"]

    APP2 --> IDB2
    APP2 --> BR
    APP2 --> SER --> HWX
    APP2 --> LOGF
    IDB2 --> VOL
```

---

## 8. Hallazgos que limitan el escalado

Detectados durante el análisis del código. Ordenados por impacto.

```mermaid
flowchart TB
    subgraph BUG1["🔴 Cola con 2 consumidores compitiendo"]
        B1A["task_process_queue: queue.consume()"]
        B1B["task_publish_mqtt: queue.consume()"]
        B1C["asyncio.Queue reparte cada item a UN solo consumidor<br/>⇒ ~50% de los lotes van a InfluxDB<br/>⇒ ~50% van a MQTT"]
        B1A --> B1C
        B1B --> B1C
    end

    subgraph FIX1["✅ Fan-out: una cola por sink"]
        F1["read_task publica en N colas<br/>o publica en un bus con suscriptores"]
        F1 --> FQ1["queue_influx → task_process_queue"]
        F1 --> FQ2["queue_mqtt → task_publish_mqtt"]
        F1 --> FQ3["queue_XXX → tarea futura"]
    end

    BUG1 --> FIX1
    classDef bad fill:#742a2a,stroke:#fc8181,color:#fff
    classDef good fill:#22543d,stroke:#68d391,color:#fff
    class B1A,B1B,B1C bad
    class F1,FQ1,FQ2,FQ3 good
```

| Severidad | Ubicación | Problema | Efecto al escalar |
|-----------|-----------|----------|-------------------|
| 🔴 Alta | `Task/task.py:263,299` | Dos tareas consumen la **misma** `asyncio.Queue` | Cada lote llega a un solo sink. Añadir un 3er sink empeora el reparto (1/3 cada uno). |
| 🔴 Alta | `Utils/utils.py` `MQTTManager.publish` | `await self._client.publish(...)` está **dentro** del `if not isinstance(payload, str)` | Si el payload ya es `str` no se publica nada, en silencio. |
| 🟠 Media | `Utils/utils.py` `MQTTManager.publish` | Rama de reconexión usa `self.settings.qos` — atributo inexistente | `AttributeError` justo en el camino de recuperación. |
| 🟠 Media | `Modbus/app.py:193-194` | `device_name.split('_')` toma sólo `part[0]_part[1]` | Rompe con nombres tipo `Modbus_DTSU_666`. Limita la convención de nombres. |
| 🟠 Media | `Task/task.py:201` | `_read_lock` cubre **todos** los dispositivos | Un bus TCP lento bloquea la lectura de los demás buses. |
| 🟡 Baja | `Modbus/read.py` | `gather` por slave sobre un mismo puerto RTU | Sin paralelismo real en serie; el tiempo crece lineal con nº de esclavos. |
| 🟡 Baja | `Database/connection.py` | `write_api` es `SYNCHRONOUS` dentro de código async | Bloquea el event loop en cada escritura de lote. |
| 🟡 Baja | `Task/task.py:247` | `sleep(self.interval/2)` | El intervalo efectivo es la mitad del configurado. |
| 🟡 Baja | `Task/task.py:141` | `initialize()` llama `_load_configs` tras crear `ModbusService` | Un fallo de InfluxDB aborta todo el arranque pese al log "continuará sin InfluxDB". |
| 🟡 Baja | `Core/watchdog.py` | Polling de `config.ini` cada 2s | Dependencia `watchdog>=6.0.0` está en `pyproject.toml` pero no se usa (inotify daría 0 polling). |

---

## 9. Arquitectura objetivo sugerida (post-fixes)

```mermaid
flowchart LR
    subgraph IN["Adquisición"]
        RD["task_read_modbus_periodic"]
        RD2["task_read_dnp3 (futuro)"]
    end

    BUS["EventBus / fan-out<br/>publish → N suscriptores"]

    subgraph OUT["Sinks (independientes, con backpressure propio)"]
        S1["InfluxSink"]
        S2["MQTTSink"]
        S3["AlarmEngine (futuro)"]
        S4["LocalBuffer / store-and-forward (futuro)"]
    end

    RD --> BUS
    RD2 --> BUS
    BUS --> S1 & S2 & S3 & S4

    S1 --> IDB[("InfluxDB")]
    S2 --> MQ["Broker"]
    S4 --> DISK[("SQLite / ficheros")]
    DISK -.reintento.-> S1

    classDef fut fill:#2d3748,stroke:#a0aec0,color:#cbd5e0,stroke-dasharray:4
    class RD2,S3,S4 fut
```
