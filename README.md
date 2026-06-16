# Black Penguin - Documentación de Avances (Semanas 1, 2, 3, 4, 5, 6, 7 y 8)

Este repositorio contiene el código fuente y la arquitectura técnica del Backend Core de **Black Penguin**, diseñada bajo un esquema SaaS Multi-tenant estricto.

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

---

## Entornos y Accesos
La API cuenta con documentación interactiva autogenerada (Swagger UI) para facilitar la visualización y prueba de los endpoints:

* **Entorno Local (Desarrollo):**
  * **API Base:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
  * **Documentación (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

* **Entorno Cloud (Producción en DigitalOcean):**
  * **API Base:** [http://206.189.118.99](http://206.189.118.99)
  * **Documentación (Swagger UI):** [http://206.189.118.99/docs](http://206.189.118.99/docs)
  *(Nota: El acceso a producción está supeditado a la apertura de puertos HTTP/HTTPS en el Cloud Firewall de DigitalOcean).*

---

## Estructura del Proyecto
El proyecto mantiene un diseño modular guiado por las mejores prácticas de la industria:

```text
BlackPenguinBackend/
│
├── .github/
│   └── workflows/
│       └── deploy.yml           # Pipeline de CI/CD para producción
│
├── app/
│   ├── api/
│   │   ├── deps.py              # Inyección de dependencias (Auth, DB)
│   │   └── v1/                  # Controladores / Endpoints
│   │       ├── auth.py          # (1) Seguridad y Autenticación
│   │       ├── superadmin.py    # (2) Gestión SaaS
│   │       ├── projects.py      # (3) Proyectos Inmobiliarios
│   │       ├── webhooks.py      # (4) Ingesta Meta/Landing
│   │       ├── leads.py         # (5) Gestión de Ventas
│   │       └── conversations.py # (6) Memoria Cognitiva IA
│   │
│   ├── core/                    # Lógica de Negocio Central y Seguridad
│   │   ├── config.py            # Variables de entorno (.env)
│   │   ├── middleware.py        # Aislamiento Multi-tenant
│   │   ├── rbac.py              # Control de Roles y Permisos
│   │   ├── security.py          # Hashing y JWT
│   │   └── security_ans.py
│   │
│   ├── models/                  # Entidades de Datos
│   │   ├── pg_models.py         # Modelos SQLAlchemy (Postgres)
│   │   └── mongo_models.py      # Modelos Pydantic/BSON y Motor Async (Mongo)
│   │
│   ├── services/
│   │   └── storage_service.py   # Gestión de archivos y multimedia
│   │
│   └── main.py                  # Entrypoint: Configuración y Registro de Rutas
│
├── Dockerfile                   # Receta de construcción de la API
├── docker-compose.yml           # Orquestación local (PG, Mongo, Redis)
├── requirements.txt             # Dependencias de Python
└── README.md                    # Documentación del proyecto
```

---

## Stack Tecnológico Actualizado
* **Lenguajes:** Python 3.12+, Node.js 24 LTS.
* **Backend:** FastAPI (con Pydantic v2 y Uvicorn).
* **Infraestructura:** K3s, Docker, DigitalOcean Droplets.
* **Bases de Datos:** PostgreSQL 16 (Relacional), MongoDB 8.0 (Documental NoSQL), Redis 7.2 (Caché y Colas).
* **Seguridad y CI/CD:** JWT, Bcrypt, UFW, Jenkins.
---
