# Black Penguin - Documentación de Avances (Semanas 1 y 2)

Este documento resume el progreso técnico realizado durante las primeras dos semanas de desarrollo del proyecto **Black Penguin**, enfocado en la cimentación de la infraestructura y el núcleo de seguridad multi-tenant.

---

## Semana 1: Infraestructura y DevOps
**Objetivo:** Establecer un entorno de despliegue automatizado, escalable y seguro en DigitalOcean.

### Logros Técnicos:
* **Orquestación con K3s:** Instalación y configuración de un clúster de Kubernetes ligero (K3s) en un Droplet de DigitalOcean, optimizado con certificados TLS para acceso remoto seguro.
* **Contenerización de Servicios (Docker):** Implementación de una arquitectura de servicios base mediante Docker Compose:
    * **PostgreSQL 17:** Base de datos transaccional con volúmenes persistentes.
    * **MongoDB 8.0:** Almacenamiento para logs conversacionales de IA y auditoría legal.
    * **Redis 7.2:** Motor de caché y gestor de colas para tareas asíncronas.
* **CI/CD con Jenkins:** Configuración de un pipeline de integración y despliegue continuo (Zero-Downtime) que automatiza la construcción de imágenes Docker y su despliegue en K3s.
* **Storage Cloud:** Configuración inicial para la integración nativa con **DigitalOcean Spaces** (S3 Compatible) para el almacenamiento de archivos multimedia y documentos.

---

## Semana 2: Backend Core y Seguridad Multi-tenant
**Objetivo:** Desarrollar la columna vertebral lógica de la aplicación y garantizar el aislamiento de datos entre clientes.

### Logros Técnicos:
* **FastAPI Framework:** Inicialización del proyecto utilizando Python 3.12+ y FastAPI para una gestión asíncrona de alto rendimiento.
* **Middleware Multi-tenant (Crítico):** Desarrollo de una capa de software que intercepta cada petición API para:
    1. Validar el token JWT.
    2. Extraer el `company_id` (Tenant).
    3. Garantizar que un usuario solo acceda a datos de su propia organización.
* **Seguridad y Auth:**
    * Implementación de **OAuth 2.0 con JWT**.
    * Matriz de permisos inicial (Superadmin, Admin Cliente, MKT, Sales).
* **Módulo Superadmin (RF-1.1.1):**
    * Endpoints para la creación de empresas.
    * Lógica de activación de licencias basada en **validación de pagos offline**.
    * Gestión de vigencia de suscripción (fechas de inicio y fin).

---

## Estructura del Proyecto
El repositorio está organizado siguiendo las mejores prácticas de modularidad y escalabilidad para FastAPI:

```text
blackpenguin-backend/
├── app/
│   ├── main.py                 # Punto de entrada de la aplicación y registro de rutas/middlewares.
│   ├── core/
│   │   ├── config.py           # Gestión centralizada de variables de entorno (DB, Keys, JWT).
│   │   ├── security.py         # Lógica de autenticación: OAuth 2.0 y generación/decodificación de JWT.
│   │   └── middleware.py       # Middleware Multi-tenant: Garantiza el aislamiento de datos por company_id.
│   ├── api/
│   │   └── v1/
│   │       └── superadmin.py   # Módulo exclusivo MAU: Gestión de empresas y licencias (RF-1.1.1).
│   └── models/                 # Esquemas de datos (Pydantic) y modelos de persistencia (ORM).
├── requirements.txt            # Listado de dependencias (FastAPI, Uvicorn, PyJWT, Psycopg2, etc.).
└── Dockerfile                  # Configuración de imagen para despliegue en K3s/Docker.
```

---

## Stack Tecnológico Actualizado
* **Lenguajes:** Python 3.12+, Node.js 24 LTS.
* **Backend:** FastAPI.
* **Infraestructura:** K3s, Docker, DigitalOcean Droplets.
* **Bases de Datos:** PostgreSQL (Estructurado), MongoDB (NoSQL), Redis (Caché).
* **Automatización:** Jenkins.

---
