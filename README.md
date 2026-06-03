# Black Penguin - Documentación de Avances (Semanas 1, 2, 3, 4 y 5)

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

---

## Semana 2: Backend Core y Seguridad Multi-tenant
**Objetivo:** Desarrollar la columna vertebral lógica de la aplicación y garantizar el aislamiento inicial.

### Logros Técnicos:
* **Estructura FastAPI Base:** Configuración del punto de entrada asíncrono asilado en Python, utilizando Pydantic v2 para la validación de contratos de entrada y salida de datos.
* **Autenticación Centralizada:** Implementación de flujos criptográficos para contraseñas usando **Bcrypt** y generación de tokens **JWT** seguros que viajan con los claims de `role` y `company_id`.
* **Módulo Superadmin (Fase Inicial):** Creación del módulo maestro de control que permite el aprovisionamiento de nuevas desarrolladoras mediante la validación de pagos offline (manuales).

---

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

---

## Semana 4: Middleware Guardian y Aislamiento Perimetral Completo
**Objetivo:** Validar y forzar de forma automatizada las fronteras lógicas de datos (Multi-tenancy) y estabilizar el entorno de ejecución en local.

### Logros Técnicos:
* **Gobernanza por Middleware Multi-tenant:** Desarrollo de un componente interceptor HTTP global en FastAPI (`MultiTenantMiddleware`). El guardián extrae el token del header `Authorization`, descifra sus claims e inyecta dinámicamente los atributos `company_id` y `role` en el estado de la petición, aislando perimetralmente las consultas y bloqueando accesos cruzados entre desarrolladoras distintas.
* **Control de Accesos Jerárquico (RBAC):** Creación de dependencias inyectables limpias (`Depends(require_superadmin)`, `Depends(require_admin)`) utilizando el patrón funcional `RoleChecker` para blindar las rutas del sistema en cascada.
* **Resolución de Compatibilidad con Python 3.13:** Parcheo y actualización del stack técnico para corregir el error crítico de variables enumeradas en el ORM (`TypeError: Can't replace canonical symbol for '__firstlineno__'`), estabilizando SQLAlchemy a versiones compatibles con entornos modernos de compilación en Windows/Unix.
* **Entorno de Pruebas Locales Exitoso:** Configuración de un orquestador local dockerizado y rutas de utilidad técnica (`/api/v1/auth/setup-master`) para la autogeneración de esquemas de tablas e inserción automática de un Superadmin global de pruebas listo para demostraciones en vivo.

---

## Semana 5: Autorización Estricta (RBAC) y Despliegue en Producción
**Objetivo:** Finalizar la base de seguridad perimetral de roles y realizar el despliegue del entorno core unificado en la nube.

### Logros Técnicos:
* **Mapeo de Autorización (JWT + RBAC):** Implementación de la dependencia centralizada de seguridad (`app/api/deps.py`) que decodifica tokens JWT y valida en tiempo real los roles corporativos (`Superadmin`, `Admin`, `MKT`, `Sales`), emitiendo respuestas HTTP 403 automáticas ante intentos de violación de privilegios.
* **Gestión de Secretos en Entornos Seguros:** Migración absoluta de credenciales en texto plano (*hardcoded*) hacia el estándar de inyección por entorno (`.env` a través de Pydantic `BaseSettings`), protegiendo llaves criptográficas (`SECRET_KEY`) y contraseñas de bases de datos tanto en Git como en el servidor.
* **Contenerización y Despliegue Cloud (DigitalOcean):**
    * Creación del `Dockerfile` optimizado para empaquetar el código fuente sobre `python:3.11-slim`.
    * Actualización del `docker-compose.yml` para orquestar la compilación en vivo y conectar de forma interna la API (Uvicorn) con los contenedores persistentes de PostgreSQL, MongoDB y Redis en la nube.
* **Networking y Firewall:** Configuración de llaves de despliegue SSH (`Deploy Keys`) para la clonación segura del repositorio y apertura controlada de puertos a nivel de sistema operativo (`UFW`) en preparación para las reglas Inbound del Cloud Firewall.

---

## Entornos y Accesos
La API cuenta con documentación interactiva autogenerada (Swagger UI) para facilitar la visualización y prueba de los endpoints:

* **Entorno Local (Desarrollo):**
  * **API Base:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
  * **Documentación (Swagger UI):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

* **Entorno Cloud (Producción en DigitalOcean):**
  * **API Base:** `http://206.189.118.99`
  * **Documentación (Swagger UI):** `http://206.189.118.99/docs`
  *(Nota: El acceso a producción está supeditado a la apertura de puertos HTTP/HTTPS en el Cloud Firewall de DigitalOcean).*

---

## Estructura del Proyecto
El proyecto mantiene un diseño modular guiado por las mejores prácticas de la industria:

```text
blackpenguin-backend/
├── .env                    # (Ignorado en git) Variables de entorno, secretos y credenciales
├── requirements.txt        # Dependencias estrictas del sistema
├── Dockerfile              # Instrucciones de compilación de la API para la nube
├── docker-compose.yml      # Orquestador maestro de contenedores (API + DBs + Cache)
├── ddl_v2.0.sql            # Diccionario de datos y arquitectura relacional física
└── app/
    ├── __init__.py
    ├── main.py             # Punto de entrada de FastAPI y ensamblaje de rutas
    ├── core/
    │   ├── __init__.py
    │   ├── config.py       # Pydantic Settings (Lectura de .env)
    │   ├── security.py     # Hasheo de contraseñas y firmas JWT
    │   ├── rbac.py         # Clases de jerarquía funcional
    │   └── middleware.py   # Guardián interceptor Multi-tenant
    ├── models/
    │   ├── __init__.py
    │   ├── pg_models.py    # Esquemas SQLAlchemy (PostgreSQL)
    │   └── mongo_models.py # Esquemas Motor/Beanie (MongoDB)
    └── api/
        ├── __init__.py
        ├── deps.py         # Inyectables (RoleChecker, get_db, get_current_user)
        └── v1/
            ├── __init__.py
            ├── auth.py         # Login y aprovisionamiento master
            └── superadmin.py   # Gestión SaaS de empresas cliente
```

---

## Stack Tecnológico Actualizado
* **Lenguajes:** Python 3.12+, Node.js 24 LTS.
* **Backend:** FastAPI (con Pydantic v2 y Uvicorn).
* **Infraestructura:** K3s, Docker, DigitalOcean Droplets.
* **Bases de Datos:** PostgreSQL 16 (Relacional), MongoDB 8.0 (Documental NoSQL), Redis 7.2 (Caché y Colas).
* **Seguridad y CI/CD:** JWT, Bcrypt, UFW, Jenkins.
---
