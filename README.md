# Plataforma de Bots Conversacionales

SaaS multi-tenant para desplegar bots conversacionales (WhatsApp, web chat…) para múltiples negocios sobre una infraestructura común. Cada cliente ejecuta su propio runtime aislado; añadir un cliente nuevo no requiere tocar el código ni hacer un deploy.

---

## Arquitectura: el modelo de dos planos

```
┌─────────────────────────────────────────────┐
│              CONTROL PLANE                   │
│         (VM compartida — :8001)              │
│                                              │
│  Tenant & Identity · Flow Authoring          │
│  Task Scheduler · Observability              │
│  Tenant Orchestrator · Admin Panel           │
│                                              │
│            PostgreSQL (BD compartida)        │
└────────────────┬────────────────────────────┘
                 │  API (config, eventos)
      ┌──────────┼──────────┐
      ▼          ▼          ▼
 ┌─────────┐ ┌─────────┐ ┌─────────┐
 │Tenant A │ │Tenant B │ │Tenant C │
 │:8002    │ │:8003    │ │...      │
 │         │ │         │ │         │
 │Channel  │ │Channel  │ │Channel  │
 │Adapter  │ │Adapter  │ │Adapter  │
 │   ↓     │ │   ↓     │ │   ↓     │
 │Bot      │ │Bot      │ │Bot      │
 │Engine   │ │Engine   │ │Engine   │
 │   ↓     │ │   ↓     │ │   ↓     │
 │Connector│ │Connector│ │Connector│
 │Execution│ │Execution│ │Execution│
 └─────────┘ └─────────┘ └─────────┘
   DATA PLANE — misma imagen, distinta config
```

| Plano | Instancias | Qué hace |
|-------|-----------|---------|
| **Control Plane** | 1 compartido | Gestiona tenants, flows, scheduler, observabilidad, panel admin |
| **Data Plane** | 1 por cliente | Recibe mensajes, ejecuta el flow, llama a conectores, responde |

**Todos los containers del Data Plane corren la misma imagen.** Lo que diferencia a un tenant de otro es la configuración que carga al arrancar.

---

## Stack

| Pieza | Elección |
|-------|---------|
| Lenguaje | Python 3.14 |
| Framework web | FastAPI + uvicorn |
| Gestor de dependencias | [uv](https://docs.astral.sh/uv/) |
| BD Control Plane | PostgreSQL 16 |
| Estado local Data Plane | SQLite (por container) |
| Linter / formatter | ruff |
| Type checking | mypy |
| Tests | pytest |

---

## Inicio rápido

### Prerrequisitos

```bash
# uv (gestor de dependencias)
curl -LsSf https://astral.sh/uv/install.sh | sh

# o con pip
pip install uv
```

### Dev local (sin Docker)

```bash
# 1. Instalar dependencias
uv sync

# 2. Arrancar el Control Plane  →  http://localhost:8001
make run-control-plane

# 3. Arrancar el Data Plane con un tenant de desarrollo
TENANT_CONFIG_PATH=tests/configs/dev_tenant.yaml make run-data-plane
# →  http://localhost:8002
```

### Stack completo con Docker Compose

```bash
# Levanta Control Plane + Data Plane + PostgreSQL
make up

# Parar (conserva la BD)
make down

# Parar y borrar la BD
make clean
```

Puertos por defecto:

| Servicio | Puerto |
|---------|--------|
| Control Plane | `localhost:8001` |
| Data Plane | `localhost:8002` |
| PostgreSQL | `localhost:5433` |

---

## Estructura del proyecto

```
.
├── control_plane/          # Plano de control (gestión de la plataforma)
│   ├── main.py             # FastAPI app · /health
│   └── Dockerfile
│
├── data_plane/             # Plano de datos (runtime del bot por tenant)
│   ├── main.py             # FastAPI app · lifespan · /health
│   ├── config.py           # TenantConfig — carga el YAML de tenant
│   ├── engine/
│   │   ├── bot.py          # Bot — orquestador central
│   │   ├── interpreter.py  # Intérprete de estados y transiciones
│   │   ├── flow.py         # Dataclasses del flow + cargador YAML
│   │   ├── outputs.py      # Output types (Text, Buttons, List…)
│   │   └── degradation.py  # Degradación de outputs según capabilities del canal
│   ├── ports/
│   │   ├── channel_adapter.py  # ABC ChannelAdapter
│   │   ├── connector.py        # ABC ConnectorPort
│   │   └── state_store.py      # ABC StateStorePort
│   ├── adapters/
│   │   ├── channel/
│   │   │   ├── whatsapp.py     # WhatsAppAdapter (Cloud API v19)
│   │   │   ├── http_dev.py     # HttpDevChannelAdapter (dev local)
│   │   │   └── factory.py      # channel_factory(config) → (adapter, router)
│   │   ├── connectors/
│   │   │   ├── google_calendar/  # GoogleCalendarAdapter
│   │   │   │   ├── adapter.py    # Implementa CalendarConnector
│   │   │   │   ├── client.py     # Auth service account (thread-local)
│   │   │   │   ├── engine.py     # compute_slots() — función PURA
│   │   │   │   ├── repository.py # Fetches crudos de Calendar API
│   │   │   │   ├── mutations.py  # crear/cancelar/confirmar/marcar eventos
│   │   │   │   ├── queries.py    # Lecturas de alto nivel
│   │   │   │   └── parser.py     # Parseo de description + normalización
│   │   │   └── mock_calendar.py  # MockCalendarAdapter (tests)
│   │   └── state_store/
│   │       ├── sqlite.py         # SQLiteStateStore (producción)
│   │       └── in_memory.py      # InMemoryStateStore (tests)
│   └── connectors/
│       ├── registry.py           # ConnectorRegistry: categoría → implementación
│       ├── circuit_breaker.py    # Circuit breaker con estados CLOSED/OPEN/HALF
│       └── categories/
│           ├── calendar.py       # CalendarConnector ABC
│           └── notification.py   # NotificationConnector ABC
│
├── shared/
│   └── domain/
│       ├── messages.py     # InternalMessage (canal-agnóstico)
│       └── conversation.py # ConversationState
│
├── flows/
│   └── peluqueria_flow.yaml   # Flow de ejemplo: reservas en peluquería
│
├── tests/
│   ├── configs/            # YAMLs de tenant para tests
│   └── flows/              # Flows de juguete para tests
│
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

---

## Flows declarativos en YAML

El bot ejecuta un **grafo de estados** definido en YAML. El mismo engine genérico ejecuta cualquier flow para cualquier cliente — el flow es un dato, no código.

```yaml
id: mi_flow_v1
initial_state: MENU

# Transiciones que aplican desde cualquier estado
global_transitions:
  - on_payload: "back_to_menu"
    target: MENU

states:
  MENU:
    on_enter:
      - action: send_interactive_buttons
        body: "¡Hola! ¿Qué quieres hacer?"
        buttons:
          - id: "menu_book"
            title: "Reservar cita"
          - id: "menu_cancel"
            title: "Cancelar cita"
    transitions:
      - on_payload: "menu_book"
        target: BOOK_SELECT_SERVICE
      - on_payload: "menu_cancel"
        target: CANCEL_SELECT
    fallback: MENU   # cualquier input no reconocido vuelve aquí

  BOOK_SELECT_SERVICE:
    on_enter:
      - action: invoke_connector   # llama al conector de calendario
        connector: calendar
        operation: get_available_days
        params:
          from_date: "{{data.today}}"
          lookahead_days: 14
        result_key: available_days
      - action: send_dynamic_options
        source_key: "available_days"
        text: "¿Qué día prefieres?"
        empty_text: "No hay días disponibles."
    transitions:
      - on_payload_prefix: "day_"
        extract_suffix_as: "selected_date"
        target: BOOK_CONFIRM
    fallback: MENU
```

### Acciones disponibles

| Acción | Descripción |
|--------|-------------|
| `send_text` | Mensaje de texto plano |
| `send_interactive_buttons` | Hasta 3 botones (WhatsApp) |
| `send_interactive_list` | Lista de opciones (hasta 10 rows en WhatsApp) |
| `send_dynamic_options` | Lista construida dinámicamente desde un resultado de conector |
| `invoke_connector` | Llama a un conector externo (calendar, payment, etc.) |

### Transiciones

| Campo | Efecto |
|-------|--------|
| `on_payload` | Coincidencia exacta del payload del botón |
| `on_payload_prefix` | Payload empieza con el prefijo; `extract_suffix_as` guarda el sufijo en `data` |
| `on_type` | Tipo de mensaje (`text`, `button`, `list`) |
| `condition` | Expresión simple sobre `data` (ej. `"data.selected_service"`) |
| `set_data` | Escribe valores en `data` antes de entrar al siguiente estado |

---

## Configuración de tenant

Cada container del Data Plane carga su configuración desde un YAML apuntado por la variable de entorno `TENANT_CONFIG_PATH`.

```yaml
# tests/configs/dev_tenant.yaml
tenant_id: mi_negocio
flow_path: flows/peluqueria_flow.yaml

channel:
  type: http_dev          # http_dev | whatsapp

connectors:
  calendar:
    type: mock            # mock | mock_calendar | google_calendar
```

### Canal WhatsApp

```yaml
channel:
  type: whatsapp
  phone_number_id: "1234567890"
  access_token: "EAAxxxxxxx"
  app_secret: "abc123"
  verify_token: "mi_verify_token"
```

### Conector Google Calendar

```yaml
connectors:
  calendar:
    type: google_calendar
    credentials_path: "/ruta/a/service_account.json"
    calendar_id: "negocio@group.calendar.google.com"
    timezone: "Europe/Madrid"
    slot_duration_min: 30
    lookahead_days_client: 14
    lookahead_days_manual: 60
    schedule:
      mon: ["10:00-14:00", "17:00-21:00"]
      tue: ["10:00-14:00", "17:00-21:00"]
      wed: ["10:00-14:00", "17:00-21:00"]
      thu: ["10:00-14:00", "17:00-21:00"]
      fri: ["10:00-14:00", "17:00-21:00"]
      sat: ["10:00-14:00"]
```

Ver [tests/configs/google_calendar_tenant.yaml.example](tests/configs/google_calendar_tenant.yaml.example) para la plantilla completa.

---

## Canales

| Canal | Clase | Uso |
|-------|-------|-----|
| **WhatsApp Cloud API** | `WhatsAppAdapter` | Producción — HMAC verificado, botones, listas, templates |
| **HTTP Dev** | `HttpDevChannelAdapter` | Desarrollo local — `POST /inbound` + `GET /messages` |

### Probar el bot localmente con HTTP Dev

```bash
# Arrancar el data plane con canal http_dev
TENANT_CONFIG_PATH=tests/configs/dev_tenant.yaml make run-data-plane

# Enviar un mensaje
curl -X POST http://localhost:8002/inbound \
  -H "Content-Type: application/json" \
  -d '{"contact_id": "user_1", "text": "hola"}'

# Leer las respuestas del bot
curl http://localhost:8002/messages
```

---

## Conectores

| Conector | Categoría | Tipo config | Estado |
|---------|-----------|-------------|--------|
| `GoogleCalendarAdapter` | `CalendarConnector` | `google_calendar` | Implementado |
| `MockCalendarAdapter` | `CalendarConnector` | `mock_calendar` | Tests |
| `MockConnector` | Genérico | `mock` | Tests / dev |

Los conectores se resuelven por **categoría** vía `ConnectorRegistry`. El flow referencia `connector: calendar`; la config del tenant decide qué implementación concreta usa.

Cross-cutting concerns aplicados centralizadamente (no en cada conector):
- Retries con backoff exponencial (tenacity)
- Circuit breaker (CLOSED → OPEN → HALF_OPEN)
- Timeouts
- Logging estructurado

---

## Comandos

```bash
make run-control-plane   # Arranca Control Plane en localhost:8001
make run-data-plane      # Arranca Data Plane en localhost:8002 (requiere TENANT_CONFIG_PATH)
make up                  # Levanta todo con Docker Compose
make down                # Para contenedores (conserva la BD)
make clean               # Para contenedores y borra la BD (down -v)
make test                # Ejecuta los tests
make lint                # ruff check + mypy
make format              # ruff format
```

---

## Tests

```bash
make test                          # todos los tests
uv run pytest tests/test_bot_engine.py -v        # un fichero concreto
uv run pytest -k "peluqueria" -v                 # por nombre
```

Los tests no necesitan credenciales ni red. Todas las APIs externas (Calendar, WhatsApp) están mockeadas.

| Fichero de test | Qué cubre |
|----------------|-----------|
| `test_bot_engine.py` | Bot + StateStore + Connector en conjunto |
| `test_interpreter_f5a.py` | Intérprete: transiciones, condiciones, set_data |
| `test_peluqueria_flow.py` | Flow completo de peluquería end-to-end |
| `test_compute_slots.py` | `compute_slots()` — función pura de disponibilidad |
| `test_connector_registry.py` | Resolución categoría → adapter + circuit breaker |
| `test_circuit_breaker.py` | Estados CLOSED / OPEN / HALF_OPEN |
| `test_degradation.py` | Degradación de outputs según capabilities del canal |
| `test_http_dev_adapter.py` | HttpDevChannelAdapter (receive, send, drain) |
| `test_dev_channel_endpoint.py` | Endpoints /inbound y /messages |
| `test_webhook_endpoint.py` | Endpoint WhatsApp (HMAC, dedup, routing) |
| `test_whatsapp_adapter.py` | WhatsAppAdapter (parseo, envío, degradación) |
| `test_google_calendar_adapter.py` | GoogleCalendarAdapter con Calendar API mockeada |
| `test_sqlite_state_store.py` | SQLiteStateStore (persistencia, aislamiento) |

---

## Estado de implementación

| Hito | Fase | Estado |
|------|------|--------|
| **M1 Foundation** | F0 — Scaffolding y stack | ✅ Cerrado |
| **M2 Bot mono-tenant** | F1 — Bot Engine standalone | ✅ Cerrado |
| | F2 — Connector framework | ✅ Cerrado |
| | F3 — Channel Adapter + WhatsApp | ✅ Cerrado |
| | F3b — HTTP Dev Channel + config tenant | ✅ Cerrado |
| | F4 — GoogleCalendarAdapter | ✅ Cerrado |
| | F5 — Vertical slice peluquería | ✅ Cerrado |
| **M3 Multi-tenant** | F6 — Tenant & Identity Service | 🔄 En curso |
| | F7 — Flow Authoring Service | ⬜ Pendiente |
| | F8 — Multi-tenancy real | ⬜ Pendiente |
| **M4 Scheduler** | F9 — Task Scheduler push | ⬜ Pendiente |
| **M5 Observabilidad** | F10 — Observabilidad básica | ⬜ Pendiente |
| | F11 — Tenant Orchestrator | ⬜ Pendiente |
| **M6 Admin Panel** | F12 — Admin Panel | ⬜ Pendiente |
| | F13 — Hardening producción | ⬜ Pendiente |

Ver [PLAN.md](PLAN.md) para los criterios de aceptación de cada fase y [arquitectura.md](arquitectura.md) para el diseño completo del sistema.
