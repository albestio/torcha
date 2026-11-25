# Torcha — Product & Technical Specification

**Documento para agentes de desarrollo**  
**Estado:** versión actualizada; incorpora la confirmación de creación programática de workspace y tabs mediante Herdr Automation 0.9.0  
**Fecha:** 19 de noviembre de 2026  
**Producto objetivo:** CLI y runtime de coordinación para equipos persistentes de agentes Pi sobre Herdr.

---

## Nota de revisión v2 — corrección importante sobre Herdr Automation

La versión anterior subestimaba la capacidad de automatización del layout de Herdr. La documentación versionada `agent-automation.mdx` confirma que Torcha **sí puede crear desde scripts el workspace y las cinco tabs** mediante la CLI/API de Herdr Automation. `workspace create` crea la primera tab y su root pane; cada `tab create` crea otra tab y su root pane. La separación entre Layout, Pane y Agent significa que `agent start` no crea layout, pero no significa que la creación del layout sea manual.

La topología recomendada queda fijada así:

1. `herdr workspace create` → workspace + Tab 1 + root pane 1.
2. Cuatro llamadas a `herdr tab create` → Tabs 2–5 + sus root panes.
3. Cinco llamadas a `herdr agent start ... --kind pi --pane ...` → cinco instancias Pi, una por pane.

Esta confirmación **no convierte Herdr Core (`hc`) en el creador del layout**: la creación de tabs pertenece a Herdr Automation (`herdr`). Core sigue siendo un runtime separado para terminales/procesos persistentes. Tampoco demuestra todavía el procedimiento de reemplazo de Pi en el mismo pane; esa prueba sigue siendo un requisito de la Fase 0.

---

## 1. Resumen ejecutivo

Torcha es una herramienta de orquestación local por proyecto que prepara y administra un equipo estable de cinco agentes de coding: un **Orchestrator** y cuatro **workers configurables**. La interfaz de trabajo es un workspace de Herdr con cinco tabs/panes identificables. En cada pane se ejecuta una instancia independiente de Pi.

La idea central es separar la **identidad y ubicación estable del agente** de la **sesión conversacional reemplazable**:

- El workspace, las tabs/panes y los nombres lógicos de los agentes representan la estructura estable del equipo.
- Cada proceso/sesión Pi puede terminarse y sustituirse por una sesión Pi nueva en el mismo pane.
- La continuidad entre sesiones se reconstruye mediante memoria persistente (Engram), un handoff explícito y la inspección del estado real del repositorio.
- Torcha coordina el ciclo de vida, verifica los handoffs y mantiene un registro operativo. No debe depender de que el transcript completo de Pi sobreviva.

**No es objetivo inicial** construir otro agente conversacional, sustituir Pi, implementar un terminal propio ni replicar las capacidades internas de Herdr. Torcha coordina herramientas y protocolos existentes.

## 2. Objetivos y límites

### Objetivos funcionales

1. Inicializar Torcha desde la raíz de cualquier proyecto mediante `torcha init`.
2. Detectar el nombre del proyecto a partir del directorio raíz, permitiendo override explícito.
3. Crear o reutilizar un workspace Herdr dedicado al proyecto.
4. Crear cinco ubicaciones persistentes y nombradas: `orchestrator` y cuatro roles worker configurables.
5. Arrancar una instancia Pi independiente en cada pane mediante las capacidades documentadas de Herdr.
6. Entregar a cada instancia su rol, instrucciones de bootstrap, referencias a memoria y handoff anterior.
7. Consultar el estado de los agentes y controlar prompts, lectura y espera.
8. Ejecutar handoff individual, colectivo y de cierre de jornada.
9. Sustituir una sesión Pi por otra nueva conservando el pane y la identidad lógica del agente.
10. Recuperarse de fallos sin destruir una sesión antigua antes de confirmar que su handoff está persistido.

### No objetivos de la primera versión

- Crear un protocolo nuevo de terminal o un sustituto de Herdr Core.
- Implementar un gestor de terminales o un layout propio: Torcha debe utilizar las primitivas públicas de Layout, Pane y Agent de Herdr Automation.
- Compartir automáticamente el contexto conversacional completo entre agentes.
- Tratar los subagentes internos de `pi-subagents-community` como si fueran panes independientes de Herdr.
- Asumir que Core conoce el uso de contexto/token de Pi sin que Pi o una extensión lo reporte.
- Atar Torcha a una implementación concreta de Engram antes de confirmar cuál es la instalación y contrato MCP utilizados por el proyecto.

## 3. Arquitectura conceptual

```text
┌───────────────────────────────────────────────────────────────┐
│                         Torcha CLI                         │
│ init · start · status · handoff · resume · stop · destroy     │
└───────────────────────────────┬───────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────┐
│                    Torcha Orchestrator                      │
│ Config/registry · lifecycle · handoff coordinator · recovery  │
│ Context policy · validation · logs                             │
└───────────────┬──────────────────┬──────────────────┬───────────┘
                │                  │                  │
       Herdr Automation     Pi integration      Memory adapter
       Layout/Pane/Agent     + Pi extension       Engram / MCP
       workspace/tab/create hooks/events         search/store
                │                  │                  │
┌───────────────▼──────────────────▼──────────────────▼───────────┐
│                   Herdr workspace / project                    │
│                                                               │
│  Tab/pane: Orchestrator   Pi session A                         │
│  Tab/pane: Worker 1       Pi session B                         │
│  Tab/pane: Worker 2       Pi session C                         │
│  Tab/pane: Worker 3       Pi session D                         │
│  Tab/pane: Worker 4       Pi session E                         │
└───────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Project repository    │
                    │ Git, files, tests     │
                    └───────────────────────┘
```

### 3.1 Distinción esencial: Herdr App/TUI frente a Herdr Core

La investigación confirma que hay dos superficies relacionadas, pero diferentes:

**Herdr App/TUI — Herdr Automation (`herdr`)**
- Es la superficie que Torcha debe utilizar para construir y controlar el workspace visual.
- La documentación 0.9.0 de Agent Automation define tres primitivas: **Layout** (`workspace`, `tab` y topología de panes), **Pane** (control de terminal) y **Agent** (control de un coding agent reconocido).
- `herdr workspace create` crea un workspace, su primera tab y el root pane de esa tab.
- `herdr tab create` crea una tab adicional y su root pane. Por tanto, un workspace de cinco agentes requiere una creación de workspace y cuatro creaciones de tab; no hacen falta `pane split` si se quiere un solo agente por tab.
- `herdr agent start` inicia un agente soportado dentro de un pane shell ya existente. No crea ni divide layout.
- La CLI devuelve JSON con los identificadores reales. Torcha debe capturarlos y persistirlos.
- La documentación permite ejecutar estas operaciones desde scripts; no se trata de una API privada ni de una capacidad de Herdr Core.

**Herdr Core (`hc`)**
- Es un runtime de terminales persistentes: ejecuta procesos dentro de terminales que pueden seguir vivos cuando se cierra el cliente.
- Expone su propia API y eventos; `hc schema` genera el esquema OpenRPC.
- Los estados semánticos de Core se reportan desde el programa mediante OSC 7501 (Program Status Protocol). Core no debe inferir el estado semántico leyendo el texto de pantalla ni reconociendo marcas de agentes.
- `hc run --bg` crea terminales administradas por Core. Esto no demuestra por sí solo que una terminal creada con `hc run` se pueda insertar o asociar a un pane ya existente de Herdr TUI.

**Decisión de arquitectura:** el camino principal de Torcha es Herdr Automation end-to-end: crear workspace y tabs mediante `herdr workspace create` / `herdr tab create`, y después iniciar Pi en cada root pane mediante `herdr agent start <name> --kind pi --pane <pane_id>`. Herdr Core (`hc`) es una capa distinta y opcional para procesos terminales independientes; no es necesario para construir el workspace de cinco tabs. No asumir que una terminal `hc run` se puede insertar en un pane existente sin una operación de integración documentada.

### 3.2 Identidad estable y sesión reemplazable

Cada agente tiene una identidad lógica Torcha permanente dentro del proyecto (`orchestrator`, `researcher`, etc.). En cada momento esa identidad apunta a:

- un workspace y tab Herdr;
- un pane Herdr;
- un alias/nombre Herdr del agente vivo;
- un proceso Pi y un identificador de sesión Pi;
- un handoff vigente o anterior.

El alias de agente de Herdr identifica al ocupante actual de un pane y puede desaparecer cuando el agente sale o es reemplazado. Por ello, Torcha debe guardar el `pane_id` y el `agent_id` propios; no debe usar el alias Herdr como única identidad persistente.

## 4. Modelo de agentes

### 4.1 Equipo inicial

| ID lógico | Nombre visible inicial | Responsabilidad |
|---|---|---|
| `orchestrator` | Orchestrator | Descomponer objetivos, asignar trabajo, coordinar dependencias, integrar resultados y mantener visión global. |
| `worker_1` | Configurable | Rol definido por el usuario/proyecto. |
| `worker_2` | Configurable | Rol definido por el usuario/proyecto. |
| `worker_3` | Configurable | Rol definido por el usuario/proyecto. |
| `worker_4` | Configurable | Rol definido por el usuario/proyecto. |

Los nombres y roles worker deben poder cambiarse en configuración sin modificar el motor de lifecycle.

### 4.2 Registro de agente (propuesta)

Ejemplo de estructura lógica; el esquema final debe versionarse:

```json
{
  "agent_id": "developer",
  "role": "Implementación de funcionalidades",
  "display_name": "Developer",
  "workspace_id": "<herdr-workspace-id>",
  "tab_id": "<herdr-tab-id>",
  "pane_id": "<herdr-pane-id>",
  "herdr_agent_name": "developer",
  "pi_session_id": "<current-pi-session-id>",
  "previous_pi_session_id": "<previous-pi-session-id>",
  "lifecycle": "ready",
  "last_handoff_id": "<handoff-id-or-null>",
  "updated_at": "<ISO-8601>"
}
```

Estados internos recomendados de Torcha (no confundir con estados oficiales de Herdr):

- `uninitialized`
- `pane_ready`
- `starting`
- `bootstrapping`
- `ready`
- `working`
- `blocked`
- `handoff_preparing`
- `handoff_prepared`
- `restarting`
- `failed`
- `stopped`
- `unknown`

Mapear a los estados que Herdr exponga; conservar el estado interno de transición cuando Torcha esté realizando una operación.

## 5. Inicialización del proyecto

### 5.1 Comando principal

```bash
cd /path/to/project
torcha init
```

Comportamiento esperado:

1. Resolver y canonicalizar el directorio actual.
2. Detectar nombre de proyecto desde el nombre de la carpeta; permitir `--name` para override.
3. Verificar que el directorio es un proyecto utilizable y que Herdr, Pi y el backend de memoria configurado están disponibles.
4. Crear `.torcha/` y su configuración inicial, sin sobrescribir archivos existentes.
5. Crear o localizar el workspace Herdr dedicado al proyecto.
6. Si es nuevo, ejecutar `herdr workspace create`; capturar `workspace`, `tab` y `root_pane.pane_id` de su respuesta JSON.
7. Crear cuatro tabs adicionales con `herdr tab create`; capturar en cada respuesta `tab` y `root_pane.pane_id`.
8. Asignar labels a las tabs y nombres de agente válidos; guardar el mapping de IDs en el registry.
9. Arrancar Pi en cada pane mediante `herdr agent start <agent-name> --kind pi --pane <pane_id>` y verificar readiness.
10. Entregar a cada Pi el prompt de bootstrap correspondiente.
11. Esperar confirmación explícita de que el agente ha terminado bootstrap y está preparado.

`init` debe ser idempotente: una segunda ejecución inspecciona y reconcilia el estado, no duplica workspaces, tabs o agentes sin avisar. Añadir `--dry-run` y una opción de reparación explícita.

### 5.2 Layout Herdr: creación automatizada de workspace y cinco tabs

La documentación versionada de Herdr 0.9.0 confirma que la creación del layout se puede realizar desde scripts mediante la CLI de Herdr Automation. Las operaciones relevantes son:

- `herdr workspace create`: crea un workspace y, automáticamente, su primera tab y root pane.
- `herdr tab create`: crea una tab adicional y su root pane.
- `herdr pane split`: crea un pane adicional dentro de una tab/layout; no es necesario para Torcha si cada tab aloja un solo agente.

La respuesta de `workspace create` contiene `.result.workspace`, `.result.tab` y `.result.root_pane`. La respuesta de `tab create` contiene `.result.tab` y `.result.root_pane`. **Los IDs deben extraerse de las respuestas JSON; nunca se deben fabricar ni predecir.**

Ejemplo ilustrativo de creación del workspace y extracción del primer pane:

```bash
created=$(herdr workspace create \
  --cwd "$PWD" \
  --label "$(basename "$PWD")" \
  --no-focus)

workspace_json=$(printf '%s\\n' "$created" | jq -c '.result.workspace')
first_tab_json=$(printf '%s\\n' "$created" | jq -c '.result.tab')
first_pane_id=$(printf '%s\\n' "$created" | jq -r '.result.root_pane.pane_id')
```

Crear las cuatro tabs restantes. Para cada una, conservar el objeto `tab` completo y extraer el `pane_id` documentado:

```bash
created=$(herdr tab create --label researcher --no-focus)
researcher_tab_json=$(printf '%s\\n' "$created" | jq -c '.result.tab')
researcher_pane_id=$(printf '%s\\n' "$created" | jq -r '.result.root_pane.pane_id')

created=$(herdr tab create --label developer --no-focus)
developer_tab_json=$(printf '%s\\n' "$created" | jq -c '.result.tab')
developer_pane_id=$(printf '%s\\n' "$created" | jq -r '.result.root_pane.pane_id')

created=$(herdr tab create --label auditor --no-focus)
auditor_tab_json=$(printf '%s\\n' "$created" | jq -c '.result.tab')
auditor_pane_id=$(printf '%s\\n' "$created" | jq -r '.result.root_pane.pane_id')

created=$(herdr tab create --label tester --no-focus)
tester_tab_json=$(printf '%s\\n' "$created" | jq -c '.result.tab')
tester_pane_id=$(printf '%s\\n' "$created" | jq -r '.result.root_pane.pane_id')
```

**Nota de implementación:** la documentación confirma que se devuelven los objetos `.result.workspace` y `.result.tab`, además de `.result.root_pane.pane_id`. El ejemplo conserva los objetos completos de workspace y tab en lugar de inventar nombres de campos internos que deben descubrirse en el schema real.

Para Torcha, conviene encapsular estas operaciones en `HerdrLayoutAdapter.create_workspace()` y `HerdrLayoutAdapter.create_tab()`. El adapter debe validar que la respuesta contiene los IDs requeridos antes de continuar. Si falla una creación a mitad del proceso, el registry debe guardar los recursos ya creados para permitir reconciliación y reintento, en lugar de crear duplicados.

La estructura resultante es un workspace con cinco tabs y cinco root panes, uno por agente:

```text
Workspace: <project>
├── Tab: Orchestrator  └── root pane → Pi
├── Tab: Researcher    └── root pane → Pi
├── Tab: Developer     └── root pane → Pi
├── Tab: Auditor       └── root pane → Pi
└── Tab: Tester        └── root pane → Pi
```

No se requiere `pane split` para esta topología. Usarlo solo si un agente necesita terminales auxiliares adicionales.

### 5.3 Arranque Pi

La documentación de Agent Automation muestra el patrón:

```bash
herdr agent start developer --kind pi --pane "$PANE_ID"
```

El comando requiere un pane shell disponible: el shell debe tener el foreground y no debe haber otro comando, editor o agente ocupándolo. El éxito significa que Herdr ha detectado el agente esperado en ese mismo terminal y lo considera listo para entrada interactiva. El arranque documentado tiene timeout por defecto y permite configurar `--timeout`.

Torcha debe comprobar el resultado de `agent start`, y no limitarse a asumir que enviar el comando equivale a que Pi esté listo.

## 6. Bootstrap de cada sesión Pi

Cada nueva sesión recibe un prompt inicial construido por Torcha con:

- identidad lógica y rol;
- nombre del proyecto y ruta raíz;
- límites y permisos del rol;
- instrucciones de uso de Engram;
- referencia y ruta del handoff anterior, si existe;
- instrucciones para inspeccionar Git y el estado real del repositorio;
- criterios de finalización del bootstrap.

### Protocolo recomendado

1. Confirmar identidad/rol y raíz del proyecto.
2. Consultar Engram con el contexto del proyecto, rol y objetivo actual.
3. Leer el handoff vigente del propio agente.
4. Leer referencias a handoffs o decisiones de otros agentes que el Orchestrator haya compartido.
5. Inspeccionar `git status`, rama, commits recientes y cambios relevantes; no asumir que el repositorio coincide con el handoff.
6. Inspeccionar los archivos/test relevantes para validar el estado descrito.
7. Detectar divergencias entre memoria/handoff y repositorio; el estado del repositorio prevalece para describir el código actual.
8. Responder con un resumen de recuperación y declarar `READY` solo cuando pueda continuar con seguridad.

`READY` es un protocolo de aplicación de Torcha, no un estado nativo garantizado de Pi o Herdr. Se puede representar mediante una respuesta estructurada o metadata/evento del agente. No inventar un estado Herdr nuevo sin registrarlo a través de la API admitida.

## 7. Memoria persistente y handoffs

### 7.1 Separación de responsabilidades

| Artefacto | Qué conserva | Qué no debe sustituir |
|---|---|---|
| Engram | Conocimiento duradero: decisiones, convenciones, hechos del proyecto, aprendizajes y referencias reutilizables. | El estado preciso de una tarea que se interrumpe ahora. |
| Handoff | Estado operativo de una tarea en un momento concreto: objetivo, progreso, archivos, decisiones recientes, bloqueos y siguiente acción. | La memoria acumulativa ni el estado real del repositorio. |
| Sesión Pi | Transcript/contexto conversacional de una ejecución concreta. | La continuidad de largo plazo. |
| Registry Torcha | IDs, ubicaciones, estado de lifecycle y referencias a sesiones/handoffs. | Memoria semántica del agente. |
| Git/repo | Estado real versionado y cambios locales del proyecto. | Decisiones o contexto no reflejados en el código. |

### 7.2 Contrato de handoff

El handoff debe ser autocontenido, versionado y fácil de validar. Propuesta de campos mínimos:

```yaml
schema_version: 1
handoff_id: "<uuid>"
project: "<project-name>"
agent_id: "developer"
role: "Implementación de funcionalidades"
created_at: "<ISO-8601>"
source_pi_session_id: "<session-id>"
status: "prepared"
objective: "<objetivo actual>"
current_state: "<resumen concreto>"
completed:
  - "<trabajo completado>"
in_progress:
  - "<trabajo en curso>"
next_actions:
  - "<siguiente paso verificable>"
files_touched:
  - path: "src/example.ts"
    reason: "<motivo>"
decisions:
  - "<decisión y justificación>"
blockers:
  - "<bloqueo o vacío>"
validation:
  commands_run:
    - "<comando>"
  results:
    - "<resultado>"
git:
  branch: "<branch>"
  head: "<commit>"
  status_summary: "<resumen>"
engram_refs:
  - "<memory-id-or-reference>"
```

No exigir que todos los campos contengan datos; usar listas vacías y valores explícitos cuando no aplique. No guardar secretos, credenciales ni variables de entorno sensibles en el handoff.

### 7.3 Handoff transaccional de dos fases

**Fase A — preparar**

1. Torcha solicita al agente un handoff formal.
2. Pi revisa su tarea, actualiza Engram con conocimiento duradero y escribe el handoff en una ruta temporal o nueva versión.
3. Pi devuelve un identificador/ruta y un resumen de confirmación.
4. Torcha comprueba que el artefacto existe, se puede leer, pasa validación de esquema y contiene el `agent_id`, `project` y `source_pi_session_id` esperados.
5. Torcha opcionalmente calcula checksum y registra el artefacto como `prepared`.

**Fase B — sustituir**

6. Solo después de validar la Fase A, Torcha cierra la sesión/proceso Pi anterior.
7. Devuelve el pane al prompt shell disponible, si el lifecycle de Herdr lo requiere.
8. Inicia una sesión Pi nueva en el mismo pane con el mismo rol.
9. Pasa la referencia del handoff y las instrucciones de bootstrap.
10. La nueva sesión consulta Engram, valida el estado real del repo y confirma `READY`.
11. Torcha actualiza el registry con el nuevo `pi_session_id` y el handoff consumido.

**Regla de seguridad:** si falla la escritura, validación o confirmación del handoff, no terminar la sesión anterior. Si falla el arranque nuevo, conservar el handoff y permitir reintento/rollback; nunca marcar como completado un handoff no verificado.

### 7.4 Fin de jornada y handoff colectivo

`torcha handoff --all` debe coordinar la preparación de los cinco agentes. Primero solicita y valida los cinco handoffs; después realiza sustituciones o deja las sesiones cerradas/preparadas según la política seleccionada. No interrumpir a todos simultáneamente sin recoger su estado.

Para reducir conflictos, reiniciar de forma secuencial o con concurrencia limitada configurable. El Orchestrator debe recibir un resumen agregado con el estado de cada worker, handoff ID, bloqueos y tareas pendientes.

Al día siguiente, `torcha start` o `torcha resume --all` puede reconstruir el equipo y lanzar sesiones Pi nuevas que consuman los handoffs guardados. Esto es distinto de reanudar el transcript nativo de una sesión antigua.

## 8. Comunicación e integración: opciones verificadas

### 8.1 Herdr TUI: CLI y Socket API

La documentación de Agent Automation presenta Herdr como una capa de automatización que puede ser controlada desde scripts u otros agentes. Para Torcha, las superficies principales son:

1. **CLI `herdr`:** primera opción para scripts, creación del layout, operaciones de pane y lifecycle de agentes. Es la ruta más simple de implementar y depurar.
2. **Socket API local:** opción para un cliente propio que necesite request/response directos y suscripciones persistentes a eventos.
3. **Agent skill:** instrucciones para que un agente use las capacidades de Herdr desde su propio pane; útil como mecanismo complementario, no como sustituto del controlador Torcha.

El socket transport documentado es newline-delimited JSON sobre socket local: Unix domain socket en Unix y named pipe en Windows. La CLI puede exportar el esquema instalado con:

```bash
herdr api schema
herdr api schema --json
herdr api schema --output herdr-api.schema.json
```

La guía 0.9.0 de Agent Automation documenta explícitamente los comandos CLI `herdr workspace create`, `herdr tab create`, `herdr pane split`, `herdr agent start`, `herdr agent get`, `herdr agent rename`, `herdr agent prompt`, `herdr agent send-keys`, `herdr agent wait` y `herdr agent read`, además de los comandos de pane para ejecutar, enviar entrada, leer y esperar salida.

La documentación de Socket API expone las operaciones equivalentes mediante métodos request/response y eventos. Entre los nombres documentados en esa superficie se encuentran operaciones de workspace/tab/pane/agent y reporting como `pane.report_agent` y `pane.report_agent_session`. Los nombres de métodos y parámetros deben obtenerse del schema de la versión instalada; no asumir que el nombre de un subcomando CLI coincide literalmente con el método socket.

Para Torcha, la recomendación es implementar primero con CLI y JSON de salida; encapsular llamadas en un adaptador `HerdrTuiAdapter`. Adoptar el socket directamente solo si se necesita una suscripción persistente a eventos o una integración más eficiente. No duplicar el protocolo: generar/leer el schema de la versión instalada.

### 8.2 Herdr Core: CLI, OpenRPC y OSC 7501

Core es otra interfaz y otro runtime. Su documentación pública indica:

- `hc run` / `hc run --bg` para ejecutar procesos.
- `hc ls`, `hc get`, `hc read`, `hc send`, `hc wait`, `hc attach` para inspección/control.
- `hc schema` para generar la especificación OpenRPC.
- `hc events` para observar eventos.
- `hc connect` para transportar el protocolo por stdin/stdout, incluso a través de SSH.
- OSC 7501 para que el propio programa informe estados semánticos como `working`, `done` o `blocked`.

Ejemplo de reporte OSC publicado por Core:

```bash
printf '\e]7501;state=blocked:app=my-agent\e\\'
```

No asumir que `herdr agent` y `hc` comparten los mismos IDs, lifecycle, sockets o API. Implementar adaptadores separados si Torcha termina necesitando ambas superficies.

### 8.3 Integración oficial Herdr–Pi

Herdr documenta una integración Pi instalable mediante:

```bash
herdr integration install pi
herdr integration status
```

La integración instala una extensión en `~/.pi/agent/extensions/herdr-agent-state.ts` (o en el directorio indicado por `PI_CODING_AGENT_DIR`). La documentación actual indica que las integraciones pueden reportar identidad nativa de sesión y, para Pi, estado del agente; la página de integraciones explica que los informes de estado llegan mediante `pane.report_agent` y que la referencia de sesión puede llegar mediante `pane.report_agent_session`.

Esto es importante: la integración de Pi con Herdr TUI no debe confundirse con el protocolo OSC 7501 de Herdr Core. Son mecanismos distintos. La integración oficial puede hacer que Herdr TUI conozca el estado/identidad de Pi sin que Torcha tenga que parsear el texto de pantalla.

En el entorno de desarrollo que motivó esta especificación se observó una integración Pi identificada como v9. La documentación web consultada presenta una versión propia de la integración; no comparar esos números sin comprobar qué versión/build los define. En cada instalación, consultar `herdr integration status` y revisar el archivo realmente instalado antes de depender de detalles internos.

### 8.4 Pi y `pi-subagents-community`

`pi-subagents-community` es una extensión de Pi para subagentes autónomos y workflows: agentes especializados en sesiones aisladas, ejecución en background o bloqueante, steering durante la ejecución, tipos de agente propios y workflows deterministas (`agent()`, `parallel()`, `pipeline()`). La ficha del paquete también documenta eventos de extensión como:

- `subagents:created`, `subagents:started`, `subagents:completed`, `subagents:failed`, `subagents:steered`, `subagents:compacted`;
- `subagents:usage`, con metadatos de uso por mensaje y agentes;
- `subagents:disposed`, al terminar el cierre de la extensión.

La ficha consultada documenta `contextUsage.percent` en el contexto de la visualización/telemetría de uso. Este tipo de evento podría ser útil para que una extensión Pi notifique a Torcha o dispare una política de handoff, pero debe verificarse el contrato exacto de eventos y cómo se accede a `contextUsage` en la versión fijada.

**Límite fundamental:** estos subagentes son sesiones administradas por la extensión dentro del ecosistema Pi. No son automáticamente las cinco tabs/panes Herdr del diseño de Torcha. Se pueden usar como capacidad adicional dentro de un worker, pero no reemplazan el equipo externo de cinco sesiones Pi.

Instalación documentada:

```bash
pi install npm:pi-subagents-community
```

La ficha advierte que los paquetes Pi pueden ejecutar código e influir en el comportamiento del agente; revisar el código y fijar una versión antes de incorporarlo a un producto.

### 8.5 Engram / memoria

El diseño exige un backend de memoria persistente compartido entre sesiones, pero la investigación disponible no permite afirmar con seguridad qué implementación concreta de Engram está instalada en el entorno del proyecto ni cuál es su contrato exacto. Hay varios proyectos/productos con el nombre Engram y APIs diferentes.

Por tanto, Torcha debe definir una interfaz interna independiente del proveedor, por ejemplo:

```ts
interface MemoryAdapter {
  search(input: { projectId: string; agentId: string; query: string }): Promise<MemoryResult[]>;
  store(input: { projectId: string; agentId: string; content: string; metadata?: Record<string, unknown> }): Promise<MemoryWriteReceipt>;
  get?(input: { reference: string }): Promise<MemoryResult | null>;
  health(): Promise<MemoryHealth>;
}
```

Si el Engram utilizado expone herramientas MCP, la integración debe realizarse como cliente MCP con el transporte y las herramientas documentadas por esa implementación concreta. No codificar nombres de herramientas, endpoints, transporte o autenticación hasta identificar el repositorio/servidor real del usuario.

La referencia a Engram en este documento define el papel arquitectónico —memoria duradera consultable por todos los agentes—, no una API de Engram ya validada.

## 9. Monitorización de contexto y política de handoff

Core por sí solo no conoce necesariamente el consumo de contexto de Pi. La señal debe venir de Pi, de una extensión Pi compatible o de una API de sesión que exponga esa métrica.

Opciones a evaluar:

1. **Pi extension propia:** escuchar eventos de Pi y emitir a Torcha uso de contexto y lifecycle.
2. **`pi-subagents-community`:** aprovechar sus eventos de uso/compaction si la versión instalada expone los campos requeridos y el agente es un subagente de esa extensión.
3. **Herdr TUI:** usar `agent.get`/eventos para estado de agente, pero no asumir que ese estado incluye porcentaje de contexto.
4. **Core OSC 7501:** reportar estado operacional de un proceso que hable el protocolo, pero no usarlo como fuente de porcentaje de contexto sin implementar esa telemetría.

La política de handoff debe ser configurable y no fijar un umbral universal. Debe considerar:

- porcentaje de contexto disponible, si se puede obtener con fiabilidad;
- tamaño estimado de la siguiente tarea;
- estado de ejecución (no interrumpir operaciones críticas);
- si el agente está bloqueado esperando autorización;
- posibilidad de hacer handoff manual;
- tiempo de sesión o fin de jornada.

El handoff manual siempre debe estar disponible independientemente del porcentaje de contexto.

## 10. CLI propuesta

La siguiente interfaz es una propuesta de producto, no un conjunto de comandos ya implementados:

```bash
torcha init [--name PROJECT] [--dry-run]
torcha start [--all]
torcha status [--json]
torcha handoff <agent-id>
torcha handoff --all [--prepare-only]
torcha resume <agent-id>
torcha resume --all
torcha restart <agent-id>
torcha stop [--all]
torcha destroy [--keep-workspace]
torcha config validate
torcha doctor
```

Semántica:

- `init`: configura proyecto, workspace/layout y agentes iniciales.
- `start`: arranca agentes ausentes y ejecuta bootstrap; no duplicar instancias activas.
- `status`: combina registry Torcha con lecturas actuales de Herdr; mostrar discrepancias.
- `handoff`: preparar y validar un handoff; reiniciar solo tras confirmación, salvo `--prepare-only`.
- `resume`: iniciar una sesión nueva a partir del último handoff válido; no implica recuperar transcript antiguo.
- `restart`: handoff seguro + sustitución de sesión en el mismo pane.
- `stop`: detener agentes/procesos de forma controlada, sin borrar memoria ni handoffs.
- `destroy`: retirar la estructura administrada por Torcha con confirmación explícita; ofrecer conservar workspace.
- `doctor`: validar dependencias, versiones, permisos, API schema, integración Pi, conectividad de memoria y consistencia del registry.

## 11. Estructura de archivos propuesta

```text
project/
├── .torcha/
│   ├── config.yaml
│   ├── registry.json
│   ├── schema/
│   │   └── handoff.schema.json
│   ├── agents/
│   │   ├── orchestrator.yaml
│   │   ├── worker_1.yaml
│   │   ├── worker_2.yaml
│   │   ├── worker_3.yaml
│   │   └── worker_4.yaml
│   ├── handoffs/
│   │   ├── orchestrator/
│   │   ├── worker_1/
│   │   ├── worker_2/
│   │   ├── worker_3/
│   │   └── worker_4/
│   ├── logs/
│   └── state/
├── .pi/
│   └── agents/              # Solo si la configuración Pi del proyecto lo requiere
└── ...
```

Engram debe seguir siendo su propio almacenamiento/backend; no duplicar toda su base de datos dentro de `.torcha/`. En `.torcha/` solo guardar configuración, IDs/referencias, handoffs y logs operativos del proyecto.

### Configuración inicial ilustrativa

```yaml
schema_version: 1
project:
  name: auto
  root: .
herdr:
  workspace_label: auto
  create_layout: true
  tabs:
    - agent_id: orchestrator
      label: Orchestrator
    - agent_id: worker_1
      label: Researcher
    - agent_id: worker_2
      label: Developer
    - agent_id: worker_3
      label: Auditor
    - agent_id: worker_4
      label: Tester
pi:
  executable: pi
  kind: pi
  bootstrap_timeout_ms: 120000
memory:
  provider: configured-adapter
handoff:
  automatic: false
  context_threshold: null  # Sin valor predeterminado hasta validar telemetría
  verify_before_restart: true
  restart_concurrency: 1
```

Los roles del ejemplo son perfiles sugeridos, no roles obligatorios.

## 12. Requisitos no funcionales

- **Idempotencia:** repetir `init` o `start` no duplica recursos.
- **Recuperabilidad:** registry reconstruible parcialmente a partir de `herdr api snapshot`, listados y lecturas autoritativas.
- **Trazabilidad:** cada transición de lifecycle y cada handoff queda registrado con timestamp e IDs.
- **Atomicidad lógica:** no reemplazar la sesión antigua antes de validar handoff.
- **Aislamiento:** cada agente tiene su propia sesión Pi; las rutas de trabajo compartidas deben coordinarse para evitar ediciones concurrentes incompatibles.
- **Seguridad:** no almacenar secretos en prompts/handoffs/logs; revisar paquetes/extensiones de terceros; validar rutas antes de borrar.
- **Compatibilidad:** obtener los schemas de la versión instalada de Herdr/Herdr Core en vez de depender de métodos no disponibles en esa versión.
- **Observabilidad:** distinguir estado reportado, estado inferido y estado desconocido; no presentar `unknown` como `idle`.
- **Portabilidad:** abstraer el transporte y los comandos por adaptadores; primera plataforma objetivo puede ser Linux, sin cerrar el diseño a macOS/Windows.

## 13. Fases de implementación

### Fase 0 — Spike de integración (obligatoria)

1. Crear workspace Herdr desde CLI y capturar workspace, primera tab y root pane.
2. Crear cuatro tabs adicionales mediante `herdr tab create`; capturar tab y root pane de cada respuesta.
3. Verificar que el workspace contiene cinco tabs y que cada tab conserva su pane raíz.
4. Arrancar Pi en uno de los panes con `herdr agent start --kind pi --pane <pane_id>`.
5. Verificar lectura, prompt, wait y estado mediante Herdr.
6. Comprobar que el pane permanece y puede recibir una nueva sesión Pi tras cerrar la anterior.
6. Verificar que la integración Pi reporta estado y session ID en la versión instalada.
7. Documentar cómo se obtiene el ID de sesión Pi nueva y cómo se inicia una conversación nueva sin `--resume`.

**Criterio de salida:** Torcha crea desde script un workspace con cinco tabs/panes, inicia Pi en cada pane y puede sustituir una sesión por otra en el mismo pane, conservando la ubicación y detectando el nuevo ocupante.

### Fase 1 — `torcha init`

- CLI, configuración, registry y adaptador Herdr TUI.
- Workspace y cinco tabs/panes.
- Arranque y bootstrap de cinco agentes.
- `status` y `doctor`.

### Fase 2 — Handoff individual

- Contrato de handoff y validación.
- Memoria adapter.
- Flujo transaccional prepare/verify/replace/bootstrap.
- Recuperación ante fallos y pruebas de interrupción.

### Fase 3 — Handoff colectivo y jornada

- `handoff --all`, informe del Orchestrator.
- Reinicio secuencial/concurrencia limitada.
- Reapertura al día siguiente desde handoffs.

### Fase 4 — Telemetría y automatización

- Extensión Pi/telemetría de contexto.
- Política de handoff configurable.
- Métricas, notificaciones y umbrales adaptativos.

### Fase 5 — Subagentes internos opcionales

- Evaluar `pi-subagents-community` dentro de cada sesión Pi para tareas paralelas internas.
- Mantener clara la separación entre agentes de primer nivel (cinco panes Torcha) y subagentes internos de Pi.

## 14. Pruebas de aceptación

1. `torcha init` crea exactamente un workspace dedicado y cinco panes, sin duplicar recursos en una segunda ejecución.
2. Los IDs reales de workspace/tab/pane quedan guardados y pueden reconciliarse después de reiniciar Torcha.
3. Cada pane inicia el agente Pi esperado y Herdr identifica el agente correcto.
4. Un worker puede recibir un prompt, trabajar, ser leído y esperar a un estado terminal sin que Torcha lea directamente el transcript interno de Pi.
5. Una sesión Pi puede ser sustituida por una nueva en el mismo pane, manteniendo `agent_id`, rol y ubicación.
6. El handoff anterior queda validado antes de terminar la sesión anterior.
7. Si la escritura/validación del handoff falla, la sesión antigua permanece viva.
8. Si la nueva sesión falla al arrancar, el handoff persiste y la operación puede reintentarse.
9. La sesión nueva inspecciona el repositorio y detecta cambios no descritos en el handoff.
10. `handoff --all` no pierde el estado de ningún agente si uno de los cinco falla.
11. Los estados desconocidos o no reportados se muestran como `unknown`, no como `idle`.
12. Las métricas de contexto solo se muestran si proceden de una fuente verificada.

## 15. Riesgos y preguntas técnicas abiertas

| Tema | Qué está validado | Qué debe probarse antes de implementarlo |
|---|---|---|
| Layout Herdr | Herdr Automation 0.9.0 documenta `workspace create` y `tab create`; cada uno devuelve su root pane, y la creación se puede ejecutar desde scripts. | Confirmar nombres de campos JSON y comportamiento de `--label`, `--no-focus`, workspace targeting y limpieza parcial en la versión instalada. |
| Pi en pane | `herdr agent start --kind pi --pane <id>` está documentado. | Inicio, cierre y reinicio de Pi en el mismo pane sin perder la topología. |
| `hc run` vs pane | `hc run --bg` crea terminal Core independiente. | Si existe mecanismo soportado para vincular/adjuntar esa terminal a un pane TUI. No asumirlo. |
| Core status | OSC 7501 y API OpenRPC documentados. | Si Torcha necesita hablar directamente con Core además de Herdr TUI. |
| Integración Pi | Extensión oficial y reporting de estado/sesión documentados. | Versión exacta, campos y comportamiento de la extensión instalada. |
| Handoff Pi | Puede implementarse como protocolo de prompt + archivo validado. | API concreta para detectar fin de turno, terminar Pi y recuperar shell prompt de forma fiable. |
| Contexto | La extensión community publica eventos de uso/compaction. | API estable para porcentaje de contexto de la sesión principal y compatibilidad con la versión de Pi fijada. |
| Engram | La memoria compartida es un requisito arquitectónico. | Identificar exactamente qué Engram usa el proyecto, herramientas MCP, transporte, autenticación y modelo de datos. |
| Sesiones nuevas | El objetivo es una conversación nueva con contexto fresco. | Comando/flags exactos de Pi para iniciar sesión nueva y obtener su nuevo ID sin reanudar el transcript antiguo. |
| Concurrencia Git | Cinco sesiones independientes pueden compartir el proyecto. | Política de worktrees/locks para evitar modificaciones simultáneas conflictivas. |

## 16. Fuentes y referencias técnicas

Las siguientes fuentes son documentación/repositorios consultados para esta especificación. Las capacidades se atribuyen a la documentación pública indicada; las decisiones de Torcha y los protocolos descritos como propuestas son diseño propio, no funcionalidades nativas de esas herramientas.

### Herdr TUI / App

1. **Agent automation — Herdr 0.9.0** — fuente versionada utilizada para confirmar creación programática de workspace/tab/root pane, primitivas Layout/Pane/Agent, requisitos de `agent start`, identidad y estados.  
   https://github.com/herdrdev/herdr/blob/master/docs/versions/0.9.0/website/src/content/docs/agent-automation.mdx
2. **Agent automation — documentación del sitio** — referencia general; la implementación debe priorizar la documentación versionada que corresponda a la versión instalada.  
   https://herdr.dev/tui/docs/agent-automation/
3. **Socket API** — API local, CLI vs socket, métodos, eventos, transporte NDJSON, reporting de estado y session ID.  
   https://herdr.dev/tui/docs/socket-api/
4. **Integrations** — integración oficial de Pi, ubicación de extensión, reporting de estado y referencias de sesión.  
   https://herdr.dev/tui/docs/integrations/
5. **Session state and restore** — persistencia y restauración de sesiones en Herdr.  
   https://herdr.dev/tui/docs/session-state/
6. **Add Herdr support to your agent** — integración de agentes propios con Herdr.  
   https://herdr.dev/tui/docs/add-herdr-support/
7. **CLI reference** — comandos `herdr agent`, targets y opciones de lectura/control.  
   https://herdr.dev/tui/docs/cli-reference/

### Herdr Core

7. **Herdr Core product/docs** — runtime persistente, `hc run`, status OSC 7501, schema OpenRPC y clientes propios.  
   https://herdr.dev/core/
8. **herdrdev/herdr-core** — repositorio oficial, README, comandos, templates, estado, eventos, máquinas y API.  
   https://github.com/herdrdev/herdr-core

### Pi y subagentes

9. **pi-subagents-community package page** — instalación, capacidades, workflows, eventos de extensión y notas de seguridad.  
   https://pi.dev/packages/pi-subagents-community
10. **Pi coding agent documentation** — documentación general del runtime Pi; consultar la versión fijada durante implementación.  
    https://github.com/badlogic/pi-mono

### Engram — identificación pendiente

11. **Engram memory server (get-engram)** — una implementación MCP de Engram con herramientas y arquitectura propias. Se incluye como referencia encontrada, no como identificación confirmada del Engram instalado en el proyecto.  
    https://github.com/get-engram/engram
12. **EngramMemory/engram-memory** — otro proyecto con nombre Engram y un conjunto de herramientas MCP distinto; demuestra por qué no se debe asumir un contrato por el nombre solamente.  
    https://github.com/EngramMemory/engram-memory
13. **Engram MCP Integration (engram.am)** — documentación de otra implementación Engram y su transporte MCP/local. No atribuirla al entorno del usuario sin confirmación.  
    https://engram.am/docs/mcp-integration

### Evidencia local de la conversación

14. **Prueba independiente de Herdr Core realizada en el entorno del usuario (19-11-2026):** `hc run --bg --name hc-smoke --no-parent ...` creó `t35` con `state=live`, `die_with_parent=false`, `parent=null`; tras cerrar el terminal cliente, otro terminal pudo listar y leer `HC_SMOKE_READY`; finalmente `hc kill hc-smoke` terminó el proceso. Esto valida persistencia frente al cierre del cliente y control remoto básico. **No** valida persistencia frente a reinicio del host/Core ni la asociación de `hc run` a tabs de Herdr TUI.
15. **Entorno local reportado en la conversación:** Herdr Core `0.1.21`; integración Pi local reportada como v9 en `~/.pi/agent/extensions/herdr-agent-state.ts`. Los números locales deben verificarse de nuevo con los comandos de estado antes de codificar contra ellos.

---

## 17. Instrucción para los agentes que implementen Torcha

Antes de escribir el producto:

1. Leer este documento completo.
2. Inspeccionar el repositorio y sus convenciones reales; no asumir stack, lenguaje ni estructura.
3. Ejecutar `herdr --help`, `herdr api schema`, `herdr integration status`, `hc --help` y `hc schema` cuando estén disponibles; guardar los schemas/versiones detectados como artefactos de investigación.
4. Completar la Fase 0 con una prueba reproducible y registrar resultados.
5. Identificar la implementación exacta de Engram configurada en el proyecto; si no se puede identificar, mantener el `MemoryAdapter` desacoplado y no inventar llamadas.
6. Marcar cada afirmación técnica del código/README como `documentada`, `verificada localmente` o `pendiente de validar`.
7. Implementar primero el camino principal de Herdr Automation (workspace/tab creation + Pane/Agent) y Pi. No incorporar `hc run` o subagentes community como dependencias obligatorias hasta demostrar que aportan una capacidad necesaria.
8. Mantener el handoff seguro como prioridad: ninguna sesión antigua se termina antes de que el handoff haya sido persistido y validado.

**Criterio rector:** Torcha debe crear y conservar mediante Herdr Automation la identidad y ubicación visual del equipo (workspace, tabs y panes), pero tratar cada conversación Pi como una ejecución efímera y reemplazable. La continuidad procede de memoria, handoff validado y estado real del repositorio, no de confiar ciegamente en el transcript anterior.
