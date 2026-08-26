# # Black Penguin - Documentación de Avances (Semanas 1 a 17)

Este repositorio contiene el código fuente, la arquitectura técnica y la documentación del proyecto **Black Penguin**, una plataforma SaaS Multi-tenant impulsada por Inteligencia Artificial y diseñada bajo un esquema de Monorepositorio (Frontend + Backend)

---

## Semana 1: Infraestructura y DevOps
**Objetivo:** Establecer un entorno de despliegue automatizado, escalable y seguro en DigitalOcean.

### Logros Técnicos:
* **Orquestación con K3s:** Instalación y configuración de un clúster de Kubernetes ligero (K3s) en un Droplet de DigitalOcean, optimizado con certificados TLS para acceso remoto seguro.
* **Contenerización de Servicios (Docker):** Implementación de una arquitectura de servicios base mediante Docker Compose para desarrollo local y aislamiento de datos:
    * **PostgreSQL 17:** Base de datos transaccional con volúmenes persistentes.
    * **MongoDB 8.0:** Almacenamiento documental para logs conversacionales de IA y auditoría legal.
    * **Redis 7.2:** Motor de caché de alta velocidad y gestor de colas para tareas asíncronas.
* **CI/CD con Jenkins:** Configuración de un pipeline de integración y despliegue continuo (Zero-Downtime) en el archivo `Jenkinsfile` que automatiza la construcción de imágenes Docker y su despliegue controlado en K3s (`staging`/`production`).
* **Storage Cloud:** Configuración inicial para la integración nativa con **DigitalOcean Spaces** (S3 Compatible) para el almacenamiento masivo de archivos multimedia.

## Semana 2: Backend Core y Seguridad Multi-tenant
**Objetivo:** Desarrollar la columna vertebral lógica de la aplicación y garantizar el aislamiento inicial.

### Logros Técnicos:
* **Estructura FastAPI Base:** Configuración del punto de entrada asíncrono asilado en Python, utilizando Pydantic v2 para la validación de contratos de entrada y salida de datos.
* **Autenticación Centralizada:** Implementación de flujos criptográficos para contraseñas usando **Bcrypt** y generación de tokens **JWT** seguros que viajan con los claims de `role` y `company_id`.
* **Módulo Superadmin (Fase Inicial):** Creación del módulo maestro de control que permite el aprovisionamiento de nuevas desarrolladoras mediante la validación de pagos offline (manuales).

## Semana 3: Capa de Datos Híbrida y Modelo de Persistencia (v2.0)
**Objetivo:** Diseñar y programar los esquemas de persistencia relacional, documental y de objetos adaptados a los planes comerciales de precios y al Gateway Multi-LLM.

### Logros Técnicos:
* **Persistencia Relacional (PostgreSQL + SQLAlchemy 2.0):**
    * Mapeo declarativo moderno del Diccionario de Datos v2.0 (`companies`, `company_specialized_agents`, `users`, `projects`, `inventory_units`, `leads`, `appointments`, `llm_global_configs`).
    * Adaptación comercial nativa: Inyección de columnas en la tabla de inquilinos para el control de planes (`Core` y `Enterprise`), límites de proyectos (`max_projects_allowed`), bolsas de minutos de llamadas telefónicas (`voice_minutes_allowance`) y feature flags de activación.
    * Integración de llaves foráneas indexadas y cascadas de borrado seguras (`ondelete="CASCADE"`) para evitar fugas de información.
* **Persistencia Documental (MongoDB + Motor/Pydantic):**
    * Modelado de la memoria a largo plazo del Agente Cognitivo (`conversations`) con soporte extendido para transcripciones de llamadas de voz, consumo granular de tokens e identificador de agentes especializados (`leasing_ai`, `financing_ai`, etc.).
    * Colección inmutable de `audit_logs` preparada para registrar eventos analíticos de uso de infraestructura y control de bloqueos automáticos por sobreconsumo.
    * Colección `compliance_logs` para resguardar de manera legal las peticiones de exclusión de contacto (*Opt-Out* / "STOP").
* **Almacenamiento de Objetos (DigitalOcean Spaces / Boto3):**
    * Definición de una estructura lógica de carpetas estrictamente condicionada al ID de la empresa (`/tenants/{company_id}/`).
    * Implementación de métodos asíncronos para la carga de archivos multimedia públicos (renders, brochures comerciales, tours virtuales) y archivos de audio privados (grabaciones de llamadas MP3 de agentes de voz accesibles solo mediante URLs firmadas temporalmente).

## Semana 4: Middleware Guardian y Aislamiento Perimetral Completo
**Objetivo:** Validar y forzar de forma automatizada las fronteras lógicas de datos (Multi-tenancy) y estabilizar el entorno de ejecución en local.

### Logros Técnicos:
* **Gobernanza por Middleware Multi-tenant:** Desarrollo de un componente interceptor HTTP global en FastAPI (`MultiTenantMiddleware`). El guardián extrae el token del header `Authorization`, descifra sus claims e inyecta dinámicamente los atributos `company_id` y `role` en el estado de la petición, aislando perimetralmente las consultas y bloqueando accesos cruzados entre desarrolladoras distintas.
* **Control de Accesos Jerárquico (RBAC):** Creación de dependencias inyectables limpias (`Depends(require_superadmin)`, `Depends(require_admin)`) utilizando el patrón funcional `RoleChecker` para blindar las rutas del sistema en cascada.
* **Resolución de Compatibilidad con Python 3.13:** Parcheo y actualización del stack técnico para corregir el error crítico de variables enumeradas en el ORM (`TypeError: Can't replace canonical symbol for '__firstlineno__'`), estabilizando SQLAlchemy a versiones compatibles con entornos modernos de compilación en Windows/Unix.
* **Entorno de Pruebas Locales Exitoso:** Configuración de un orquestador local dockerizado y rutas de utilidad técnica (`/api/v1/auth/setup-master`) para la autogeneración de esquemas de tablas e inserción automática de un Superadmin global de pruebas listo para demostraciones en vivo.

## Semana 5: Autorización Estricta (RBAC) y Despliegue en Producción
**Objetivo:** Finalizar la base de seguridad perimetral de roles y realizar el despliegue del entorno core unificado en la nube.

### Logros Técnicos:
* **Mapeo de Autorización (JWT + RBAC):** Implementación de la dependencia centralizada de seguridad (`app/api/deps.py`) que decodifica tokens JWT y valida en tiempo real los roles corporativos (`Superadmin`, `Admin`, `MKT`, `Sales`), emitiendo respuestas HTTP 403 automáticas ante intentos de violación de privilegios.
* **Gestión de Secretos en Entornos Seguros:** Migración absoluta de credenciales en texto plano (*hardcoded*) hacia el estándar de inyección por entorno (`.env` a través de Pydantic `BaseSettings`), protegiendo llaves criptográficas (`SECRET_KEY`) y contraseñas de bases de datos tanto en Git como en el servidor.
* **Contenerización y Despliegue Cloud (DigitalOcean):**
    * Creación del `Dockerfile` optimizado para empaquetar el código fuente sobre `python:3.11-slim`.
    * Actualización del `docker-compose.yml` para orquestar la compilación en vivo y conectar de forma interna la API (Uvicorn) con los contenedores persistentes de PostgreSQL, MongoDB y Redis en la nube.
* **Networking y Firewall:** Configuración de llaves de despliegue SSH (`Deploy Keys`) para la clonación segura del repositorio y apertura controlada de puertos a nivel de sistema operativo (`UFW`) en preparación para las reglas Inbound del Cloud Firewall.

## Semana 6: Ingesta Omnicanal de Leads y Webhooks
**Objetivo:** Capturar prospectos en tiempo real desde distintas fuentes publicitarias y normalizarlos para inyectarlos de forma segura en la base de datos aislada.

### Logros Técnicos:
* **Modelado de Prospectos y Diccionarios:** Creación de las tablas `leads` con control de etapas de embudo (`FunnelStage`) y `meta_form_mappings` para el control de orígenes.
* **Extracción de Datos Reales (Meta Graph API):** Implementación de peticiones asíncronas (`httpx`) para canjear identificadores de Meta Ads por datos reales de contacto de los prospectos.
* **Validación Criptográfica (X-Hub-Signature):** Blindaje del webhook mediante firmas matemáticas HMAC-SHA256 en FastAPI para prevenir ataques y la inyección de leads fraudulentos.
* **Enrutamiento Inteligente:** Mapeo automático de formularios de origen de campañas (`form_id`) hacia los proyectos inmobiliarios (`project_id`) correspondientes para cada constructora.
* **Panel de Gestión Comercial (CRUD):** Creación de endpoints (`GET /leads/` y `PUT /leads/{id}`) con aislamiento Multi-tenant estricto para que el equipo de ventas visualice sus prospectos y modifique los estados del embudo.

## Semana 7: Gestión de Leads y Pipeline de Ventas
**Objetivo:** Transformar los prospectos capturados en oportunidades de negocio reales mediante un flujo de trabajo estructurado, permisos granulares y gestión documental.

### Logros Técnicos:
* **Máquina de Estados de Ventas:** Definición e implementación de FunnelStage con transiciones validadas para garantizar la integridad del ciclo comercial desde el primer contacto hasta el cierre, evitando inconsistencias en los datos.
* **Control de Acceso Basado en Roles (RBAC):** Integración de la capa de seguridad (rbac.py) para limitar qué información de los leads puede visualizar, editar o exportar el asesor comercial frente a los permisos del gerente.
* **Servicio de Almacenamiento Dinámico (storage_service):** Desarrollo de la lógica para la gestión de archivos adjuntos (cotizaciones, planos, contratos) vinculados al expediente de cada prospecto dentro de la plataforma.
* **Consultas de Alto Rendimiento:** Optimización de queries complejas mediante SQLAlchemy para permitir el filtrado masivo de prospectos por fecha, origen, proyecto y estado del embudo, asegurando la escalabilidad del CRM.
* **Serialización Avanzada (Pydantic v2):** Refactorización de esquemas de respuesta para manejar la carga útil de los leads de forma eficiente, incluyendo campos calculados y relaciones de datos entre los proyectos inmobiliarios y los clientes.

## Semana 8: Memoria Cognitiva de IA y Optimización de CI/CD
**Objetivo:** Integrar persistencia documental asíncrona para el historial conversacional de la IA y estabilizar el pipeline de despliegue continuo (CI/CD) para entornos de producción.

### Logros Técnicos:
* **Integración Asíncrona de MongoDB (Motor):** Implementación de un db_manager (patrón Singleton) para la conexión asíncrona no bloqueante con MongoDB, permitiendo manejar el historial de la IA sin impactar el rendimiento del API Core.
* **Despliegue Automatizado Nativo (Docker):** Refactorización del flujo de CI/CD en GitHub Actions, migrando de una orquestación compleja (K3s) a un despliegue nativo con Docker, garantizando Zero-Downtime y sincronización exacta entre el repositorio y el servidor.
* **Persistencia de Memoria Cognitiva:** Diseño y registro de esquemas de datos (Pydantic v2) para Conversations y ChatMessages, integrando el aislamiento perimetral mediante tenant_id para asegurar la privacidad entre clientes.
* **Resolución de Conflictos de Dependencias:** Limpieza profunda de la estructura de paquetes, resolviendo problemas de rutas y conflictos de importación (clonación de modelos) para asegurar que la arquitectura de la API sea escalable y mantenible.
* **Sincronización de Entorno de Producción:** Implementación de flujos de trabajo de sincronización forzada (git reset --hard) y gestión de variables de entorno sin comillas, garantizando que el servidor de producción refleje fielmente los cambios realizados en el entorno local.

## Semana 9: Integración Cognitiva y Extracción Automatizada (Meta + OpenRouter)
**Objetivo:** Conectar el backend con APIs externas críticas para automatizar la captura de prospectos y dotar a la plataforma de inteligencia artificial conversacional mediante GPT 4o Mini.

### Logros Técnicos:
* **Extracción Automatizada (Meta Graph API):**
    * Refactorización del script de pruebas aislado hacia una integración nativa en FastAPI usando `httpx` para peticiones asíncronas no bloqueantes.
    * Implementación del canje en tiempo real: El webhook recibe el `leadgen_id` de Meta y el backend consulta automáticamente la Graph API (v20.0) para extraer el teléfono, correo y nombre real del prospecto.
    * Resolución de políticas estrictas de privacidad de Meta: Configuración avanzada en *Meta for Developers* para habilitar el permiso `leads_retrieval` y vinculación del *System User* con la Fanpage (ej. *I9framework* y *GHL Golf*) para sortear el error de acceso `(#100)`.
* **Memoria Cognitiva IA (PostgreSQL + MongoDB):**
    * Creación del modelo relacional `ChatMessage` en PostgreSQL, vinculado mediante llave foránea a la tabla `leads` para garantizar la persistencia del contexto histórico de cada cliente.
    * Mantenimiento de la estrategia híbrida: Los hilos interactivos en tiempo real viven en PostgreSQL, mientras que las transcripciones masivas consolidadas se respaldan en MongoDB bajo estricto aislamiento *Multi-tenant* (`company_id`).
* **Integración de GPT 4o Mini (vía OpenRouter API):**
    * Desarrollo de la capa de servicio `ai_service.py` para abstraer la comunicación con OpenRouter.
    * Creación del endpoint interactivo `POST /api/v1/conversations/chat` que inyecta un *Prompt de Sistema Maestro* (personalidad de asesor de inversiones de alto nivel), adjunta el historial cronológico del prospecto recuperado de la base de datos, y consume el modelo `openai/gpt-4o-mini`.
    * Lógica de embudo dinámica: Al interactuar con la IA, el estado del Lead (prospecto) avanza automáticamente en la base de datos (de `NEW` a `CONTACTED`).

### Semanas 10: Monorepo, Interfaz de Usuario y Despliegue CI/CD
**Objetivo:** Integrar el cliente web, conectar el modelo de Inteligencia Artificial y automatizar el despliegue a producción en DigitalOcean.
* **Estructura Monorepo:** Refactorización del repositorio para contener tanto el `frontend` como el `backend` en un mismo lugar, facilitando el control de versiones y el despliegue sincronizado.
* **Desarrollo Frontend (Angular 17+):**
  * **Landing Page:** Diseño y maquetación de la página comercial de presentación.
  * **Módulo de Autenticación:** Flujos completos de Registro (`register`) y Acceso (`login`) con manejo visual de errores (Toasts) y persistencia de sesión JWT.
  * **Chatbot UI:** Construcción de la interfaz conversacional del Copiloto de IA, incluyendo soporte nativo para **Drag & Drop** de archivos PDF y renderizado dinámico de respuestas con markdown.
* **Integración de IA (OpenRouter):** Conexión del backend con modelos de lenguaje de última generación (`gpt-4o-mini`) mediante OpenRouter, integrando la extracción en memoria de texto desde PDFs (`pypdf`) y aplicación de *Prompt Engineering* avanzado para estructurar datos comerciales en tiempo real.
* **Infraestructura y CI/CD (GitHub Actions):** * Migración del pipeline de despliegue a GitHub Actions (`deploy.yml`).
  * Contenerización del frontend en Docker usando Nginx para servir la SPA.
  * Configuración dinámica de URLs de API (`isDevMode()`) para soportar entornos locales y de producción sin cambios manuales.
  * Apertura de puertos (UFW y Cloud Firewalls) para despliegue exitoso en Droplets de DigitalOcean.

## Semana 11: Endpoints Públicos, Autenticación Stateless y Pipeline de Despliegue Incremental
**Objetivo:** Orquestar los puntos de entrada públicos (SPA), implementar el flujo de autenticación segura basada en tokens y consolidar el pipeline de CI/CD del frontend para habilitar despliegues iterativos en producción.

### Logros Técnicos y Arquitectónicos:
* **Despliegue Incremental y Continuous Delivery (`https://blackpenguin.ai/`):** Refactorización del pipeline en GitHub Actions (`deploy.yml`) para aislar la construcción de la imagen Docker del frontend. Configuración del proxy inverso (Nginx) con soporte SPA (Single Page Application) y enrutamiento dinámico (`try_files`), permitiendo al **Staff de Black Penguin** validar componentes funcionales en un entorno de producción real mediante despliegues *Zero-Downtime*.
* **Landing Page y Motor de Whitelist Nativo:** Desarrollo de los componentes estructurales de la landing page bajo arquitectura *Standalone* en Angular v17+. Se reemplazó la dependencia de servicios de terceros mediante la construcción de un motor de *Waitlist* nativo, con esquemas de validación estricta (Pydantic) en FastAPI y persistencia directa en PostgreSQL para reducir latencia y asegurar la soberanía de los datos.
* **Autenticación Stateless y Seguridad (Auth Flow):** Implementación de un sistema de control de acceso basado en JSON Web Tokens (JWT). El backend gestiona el ciclo de vida de la sesión sin estado y protege las contraseñas mediante hashing unidireccional (Bcrypt). En el frontend, se integraron *HttpInterceptors* para la inyección automática de *Bearer tokens* en los headers y *Route Guards* para aislar y proteger las vistas privadas.

## Semana 12: Arquitectura Multi-Tenant y Paneles de Control (Backoffice & Developer Dashboard)
**Objetivo:** Construir e integrar las interfaces de administración bajo un esquema estricto de Role-Based Access Control (RBAC), aislando lógicamente los entornos del Superadmin y de los Tenants (Empresas Desarrolladoras).

### Logros Técnicos y Arquitectónicos:
* **Admin Panel del Staff (Superadmin UI):** Implementación de la capa de gestión con privilegios de nivel de sistema. Se expusieron endpoints RESTful en FastAPI para el consumo de telemetría global, gestión del ciclo de vida de suscripciones y operaciones CRUD sobre los Tenants. El frontend maneja el estado de estas tablas de datos empleando flujos reactivos, optimizando las peticiones HTTP y la renderización en el DOM.
* **Developer Tenant Dashboard (Aislamiento de Contexto):** Despliegue del entorno operativo particionado lógicamente por `company_id`. La interfaz consume los endpoints del perfil cognitivo y renderiza dinámicamente el progreso del *onboarding*. Se integraron flujos de red asíncronos para canalizar *prompts* e inyectar el contexto de la empresa hacia la infraestructura de IA (LLMs) en tiempo real.
* **Sincronización del Pipeline y Ajustes de Proxy:** Ambos módulos se unificaron dentro de la build principal de la SPA. Como respuesta a pruebas en vivo del Staff, se actualizaron las directivas de Nginx (`client_max_body_size`) a través del pipeline automatizado, garantizando la correcta transferencia de payloads grandes (PDFs para entrenamiento del modelo cognitivo) superando las restricciones del proxy inverso.

## Semana 13: Onboarding Inteligente de Company y Gestión de Conocimiento

**Objetivo:** Implementar un proceso conversacional para recopilar, procesar y validar la información institucional de cada desarrolladora inmobiliaria.

### Logros Técnicos y Arquitectónicos:

- **Company Onboarding conversacional:** Desarrollo del flujo `/app/company`, mediante el cual el administrador proporciona progresivamente la información legal, comercial y operativa de su empresa.
- **Procesamiento inicial mediante URL:** Implementación de una pantalla que solicita el sitio web de la Company, extrae su contenido y presenta un resumen para validación antes de continuar con el onboarding.
- **Ingesta multimodal de información:** Incorporación de soporte para recibir datos mediante texto, URLs, documentos PDF, archivos e imágenes, centralizando el conocimiento necesario para configurar los agentes de IA.
- **Perfil estructurado de Company:** Organización de la información recopilada en campos requeridos y opcionales, incluyendo:
  - Nombre legal y nombre comercial.
  - Ubicación y trayectoria.
  - Descripción institucional.
  - Visión de la empresa.
  - Tono de comunicación.
  - Información comercial y de cumplimiento.
- **Sistema de propuestas y confirmación:** La IA puede identificar datos dentro de las fuentes proporcionadas, proponer actualizaciones y solicitar la aprobación del administrador antes de considerarlas información confirmada.
- **Indicador de progreso:** Incorporación de un panel lateral para mostrar el porcentaje de onboarding completado y distinguir entre información obligatoria, opcional y pendiente.
- **Configuración de prompts especializados:** Definición de los tres prompts principales utilizados por el agente de onboarding:
  - `Identity Prompt`: establece la identidad, propósito y comportamiento del asistente.
  - `Flow Protocol Prompt`: controla el orden de recopilación y validación de la información.
  - `Guardrails Prompt`: restringe acciones inseguras, invenciones y uso de datos no confirmados.
- **Aislamiento Multi-tenant:** Toda la información, archivos y sesiones del onboarding quedan asociados a la Company correspondiente, evitando accesos cruzados entre desarrolladoras.

---

## Semana 14: Project Onboarding y Perfil Comercial Inmobiliario

**Objetivo:** Extender el onboarding inteligente al nivel de Projects y construir una fuente de conocimiento comercial confiable para los futuros agentes de ventas.

### Logros Técnicos y Arquitectónicos:

- **Nuevo flujo de creación de Projects:** Reemplazo del formulario modal por una redirección directa al onboarding conversacional del nuevo Project.
- **Project Onboarding asistido por IA:** Implementación de la ruta `/app/projects/{project_id}/onboarding`, donde el administrador puede proporcionar información mediante texto, enlaces y documentos comerciales.
- **Extracción de información inmobiliaria:** El asistente procesa brochures, páginas web y documentos para identificar información como:
  - Nombre y descripción del Project.
  - Tipo y estado del desarrollo.
  - Ubicación.
  - Amenidades.
  - Tipologías disponibles.
  - Unidades e inventario.
  - Precios y condiciones comerciales.
  - Reglas de calificación de leads.
  - Información legal y de cumplimiento.
  - Campañas y configuración de Meta.
- **Flujo proactivo de recopilación:** El agente identifica los campos pendientes y formula preguntas específicas, evitando que el administrador tenga que determinar manualmente qué información falta.
- **Revisión y aprobación de propuestas:** Los datos extraídos no se incorporan automáticamente al perfil definitivo. Primero se presentan como propuestas que el usuario puede aprobar o rechazar.
- **Confirmación final del Project:** Una vez completada la información obligatoria, el agente solicita una validación final antes de marcar el onboarding como aprobado.
- **Redirección al detalle del Project:** Después de la aprobación, el usuario es dirigido a una vista consolidada con la información comercial recopilada.
- **Almacenamiento organizado de archivos:** Los documentos quedan separados por Company y Project, y vinculados con los mensajes donde fueron proporcionados.
- **Aislamiento de información:** Todas las consultas validan simultáneamente `company_id` y `project_id`, garantizando que cada desarrolladora acceda únicamente a sus propios Projects.

---

## Semana 15: Estabilización del Onboarding y Mejora de la Experiencia de Usuario

**Objetivo:** Corregir los problemas de navegación, actualización reactiva y visualización detectados durante las pruebas del onboarding de Company y Projects.

### Logros Técnicos y Arquitectónicos:

- **Actualización reactiva sin recargar la página:** Corrección del problema que obligaba a presionar `F5` después de procesar una URL o documento para visualizar los resultados.
- **Estabilización del listado de Projects:** Corrección del indicador de carga que permanecía activo durante la primera navegación y requería volver a seleccionar la opción del menú.
- **Estado vacío de Projects:** Incorporación de una vista informativa cuando una Company todavía no tiene Projects registrados.
- **Gestión de Projects:** Incorporación de acciones para continuar el onboarding y eliminar Projects desde el listado principal.
- **Corrección de URLs de producción:** Ajuste de la configuración del frontend para consumir los endpoints mediante HTTPS y evitar errores de contenido mixto en `blackpenguin.ai`.
- **Persistencia visual de opciones:** Las alternativas presentadas por el asistente permanecen visibles dentro del mensaje original después de que el usuario selecciona una respuesta.
- **Mejora de archivos adjuntos:** Simplificación de la interfaz para mostrar únicamente el nombre y tamaño del archivo, evitando tarjetas grandes que bloqueaban el espacio del chat.
- **Entrada de voz mediante STT:** Incorporación de un botón de micrófono junto al campo de escritura para convertir la voz del usuario en texto.
- **Reproducción de respuestas mediante TTS:** Incorporación de controles para escuchar mediante audio las respuestas generadas por el asistente.
- **Vista detallada del Project:** Preparación de una pantalla para mostrar:
  - Imagen principal.
  - Información general.
  - Ubicación y estado.
  - Inventario y unidades.
  - Métricas comerciales.
  - Campañas asociadas.
  - Claves y configuración de Meta.
- **Corrección de conflictos del onboarding:** Estabilización de los flujos de aprobación para evitar respuestas `409 Conflict` causadas por propuestas ya procesadas o estados desactualizados.
- **Mejora de consistencia visual:** Alineación de las pantallas iniciales, el chat, las opciones y los estados de carga con la identidad gráfica de Black Penguin.

---

## Semana 16: Project Demo, Operación Comercial y Sales Agent con LangGraph

**Objetivo:** Construir la base operativa para gestionar usuarios, campañas y leads, e implementar un agente comercial controlado mediante LangGraph.

### Logros Técnicos y Arquitectónicos:

- **Project Demo automático:** Cada Company nueva recibe exactamente un Project Demo con información sintética y onboarding completado al 100%.
- **Aprovisionamiento transaccional:** La creación de la Company, el usuario administrador y el Project Demo se realiza dentro de una única transacción. Si alguna operación falla, se revierte el proceso completo.
- **Creación idempotente del Demo:** El sistema evita generar más de un Project Demo para una misma Company, incluso cuando el proceso se ejecuta varias veces.
- **Control correcto de cuotas:** El atributo `max_projects` permanece exclusivamente en Company. Los Projects Demo se excluyen del cálculo del límite de Projects reales.
- **Seguridad del entorno Demo:** Los datos sintéticos no pueden:
  - Contactar personas.
  - Generar mensajes externos.
  - Activar webhooks de salida.
  - Sincronizar calendarios.
  - Consumir recursos comerciales reales.
- **Gestión de usuarios y roles:** Incorporación de la pantalla `/app/users` para administrar usuarios de la Company, roles y futuras asignaciones de Marketing y Sales.
- **Asignación de usuarios a Projects:** Preparación del modelo para determinar qué integrantes del equipo pueden trabajar con cada Project y recibir leads.
- **Módulo de Marketing:** Incorporación de la pantalla `/app/marketing` como base para visualizar campañas, formularios de Meta, atribución y resultados comerciales.
- **Módulo de Sales:** Incorporación de la pantalla `/app/sales` para consultar leads, etapas del funnel, asignaciones, conversaciones, reuniones y actividad del agente.
- **Trazabilidad comercial:** Consolidación de la relación: `Company → Project → Campaign → Lead → Conversation`
---

## Entornos y Accesos
La plataforma está estructurada como un Monorepo modular, distribuyendo de forma independiente el acceso a la aplicación de interfaz y al motor de servicios del ecosistema:

* **Entorno Local (Desarrollo):**
  * **Aplicación Web (Frontend):** [http://localhost:4200](http://localhost:4200)
  * **API Base (Backend):** [http://127.0.0.1:8000](http://127.0.0.1:8000)
  * **Documentación Interactiva (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

* **Entorno Cloud (Producción en DigitalOcean):**
  * **Aplicación Web (Frontend):** [http://206.189.118.99](http://206.189.118.99) *(Puerto default 80 / Servido por Nginx)*
  * **API Base (Backend):** [http://206.189.118.99:8000](http://206.189.118.99:8000) *(Puerto 8000 / Servido por Uvicorn)*
  * **Documentación Interactiva (Swagger UI):** [http://206.189.118.99:8000/docs](http://206.189.118.99:8000/docs)
  *(Nota: La conectividad de las peticiones HTTP desde el frontend hacia la API en producción está supeditada a la apertura definitiva del puerto de entrada 8000 en el Cloud Firewall perimetral de DigitalOcean).*

---

## Estructura del Proyecto
El proyecto mantiene un diseño modular guiado por las mejores prácticas de la industria:

```text
BlackPenguin/
├── .github/workflows/
│   └── deploy.yml               # Pipeline CI/CD automatizado hacia DigitalOcean
├── backend/                     # Backend API (FastAPI)
│   ├── Dockerfile               # Receta de construcción del Backend
│   ├── requirements.txt         # Dependencias de Python
│   └── app/
│       ├── main.py              # Entrypoint y configuración CORS
│       ├── core/                # Seguridad, Middlewares, Settings
│       ├── db/                  # Conexiones Mongo y Postgres
│       └── modules/             # Dominios (auth, ai, properties, sales...)
├── frontend/                    # Cliente Web (Angular 17+)
│   ├── Dockerfile               # Receta Multi-etapa (Node.js + Nginx)
│   ├── nginx.conf               # Configuración de Nginx para enrutamiento SPA
│   ├── package.json
│   ├── tailwind.config.js       # Diseño y sistema de clases
│   └── src/app/
│       ├── core/services/       # Lógica de conexión HTTP (auth.ts, chat.ts, toast.ts)
│       └── pages/               # Vistas de la aplicación
│           ├── landing/         # Página comercial inicial
│           ├── login/           # Interfaz de inicio de sesión
│           ├── register/        # Creación de cuentas maestras
│           └── chat/            # Interfaz interactiva de IA (Soporte PDF)
├── docker-compose.yml           # Orquestación local de Bases de Datos
└── README.md                    # Documentación del proyecto
```

---

## Stack Tecnológico Actualizado
* **Lenguajes:** Python 3.12+, TypeScript (Node.js 20+).
* **Backend:** FastAPI (con Pydantic v2 y servidor asíncrono Uvicorn).
* **Frontend:** Angular (v17+) optimizado con maquetación en Tailwind CSS y SCSS.
* **Inteligencia Artificial:** Conexión vía OpenRouter empleando modelos avanzados (`openai/gpt-4o-mini`) con procesamiento y extracción en memoria de texto desde archivos PDF (`pypdf`).
* **Bases de Datos:** PostgreSQL 17 (Aislamiento de datos relacionales/SaaS Multi-tenant), MongoDB 8.0 (Datos no estructurados/Logs conversacionales e historial de auditoría de IA) y Redis 7.2 (Caché de alta velocidad y colas de tareas).
* **Infraestructura y DevOps:** Docker (Contenerización multiplataforma), Docker Compose (Orquestación local), Nginx Alpine (Servidor proxy inverso para la SPA) y Droplets VPS de DigitalOcean.
* **Seguridad y CI/CD:** Autenticación por Tokens JWT, Encriptación Bcrypt, UFW (Ubuntu Firewall), DigitalOcean Cloud Firewalls y automatización de despliegues por medio de **GitHub Actions** (`deploy.yml`).

---
