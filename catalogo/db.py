"""Conexión a PostgreSQL y esquema de la base de datos (Listado 1 y sección V-B)."""
import psycopg

from .config import DATABASE_URL

ESQUEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id SERIAL PRIMARY KEY,
    nombre TEXT,
    fuente TEXT,
    descripcion TEXT,
    archivo TEXT UNIQUE,      -- ruta del CSV en el repositorio de origen
    columnas TEXT             -- nombres de columna separados por comas (catálogo)
);

CREATE TABLE IF NOT EXISTS versiones (
    id SERIAL PRIMARY KEY,
    dataset_id INT REFERENCES datasets(id),
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    hash_contenido TEXT,
    metadatos JSONB
);

CREATE TABLE IF NOT EXISTS columnas_version (
    id SERIAL PRIMARY KEY,
    version_id INT REFERENCES versiones(id),
    nombre_columna TEXT,
    tipo_dato TEXT,
    nulos INT
);

-- Filas versionadas con su intervalo de validez
CREATE TABLE IF NOT EXISTS registros (
    id BIGSERIAL PRIMARY KEY,
    dataset_id INT REFERENCES datasets(id),
    clave_registro TEXT NOT NULL,
    hash_fila TEXT NOT NULL,
    datos JSONB NOT NULL,
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_registros_vigencia
    ON registros (dataset_id, valid_from, valid_to);

-- Índice parcial sobre las filas vigentes: acelera la comparación con la versión siguiente
CREATE INDEX IF NOT EXISTS idx_registros_actuales
    ON registros (dataset_id) WHERE valid_to IS NULL;

-- Cambios estructurales detectados en cada versión (sección V-B)
CREATE TABLE IF NOT EXISTS cambios (
    id SERIAL PRIMARY KEY,
    version_id INT REFERENCES versiones(id),
    tipo TEXT NOT NULL,       -- columna_añadida | columna_eliminada | tipo_modificado | orden_modificado
    columna TEXT,
    detalle TEXT
);

CREATE INDEX IF NOT EXISTS idx_versiones_dataset ON versiones (dataset_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_columnas_version ON columnas_version (version_id);
CREATE INDEX IF NOT EXISTS idx_cambios_version ON cambios (version_id);
"""


def get_connection(autocommit=False):
    """Abre una conexión nueva a la base de datos configurada en .env."""
    return psycopg.connect(DATABASE_URL, autocommit=autocommit)


def init_db():
    """Crea las tablas e índices si no existen."""
    with get_connection() as conn:
        conn.execute(ESQUEMA)
        conn.commit()


def reiniciar_db():
    """Borra todas las tablas y las vuelve a crear (solo para recargar desde cero)."""
    with get_connection() as conn:
        conn.execute(
            "DROP TABLE IF EXISTS cambios, registros, columnas_version, versiones, datasets CASCADE"
        )
        conn.commit()
    init_db()
