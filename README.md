# Black Penguin - Documentación de Avances (Semanas 1, 2, 3 y 4)

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
* **Persistencia Relacional (PostgreSQL + SQLAlchemy 2.0):** * Mapeo declarativo moderno del Diccionario de Datos v2.0 (`companies`, `company_specialized_agents`, `users`, `projects`, `inventory_units`, `leads`, `appointments`, `llm_global_configs`).
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

## Estructura del Proyecto
El proyecto mantiene un diseño modular guiado por las mejores prácticas de la industria:

```text
blackpenguin-backend/
├── requirements.txt
├── docker-compose.yml (Para levantar base de datos local)
└── app/
    ├── __init__.py
    ├── main.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py
    │   ├── security.py
    │   ├── rbac.py
    │   └── middleware.py
    ├── models/
    │   ├── __init__.py
    │   ├── pg_models.py
    │   └── mongo_models.py
    └── api/
        ├── __init__.py
        └── v1/
            ├── __init__.py
            ├── auth.py
            └── superadmin.py
```

---

## Stack Tecnológico Actualizado
* **Lenguajes:** Python 3.12+, Node.js 24 LTS.
* **Backend:** FastAPI.
* **Infraestructura:** K3s, Docker, DigitalOcean Droplets.
* **Bases de Datos:** PostgreSQL (Estructurado), MongoDB (NoSQL), Redis (Caché).
* **Automatización:** Jenkins.

---
