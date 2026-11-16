import psycopg
import os

# Ajusta estas credenciales según tu instalación de PostgreSQL
DATABASE_URL = "postgresql://tfg_user:root@localhost:5432/catalogo_tfg"

def get_connection():
    return psycopg.connect(DATABASE_URL)

def init_db():
    """Crea las tablas según el Listado 1 del documento"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id SERIAL PRIMARY KEY, nombre TEXT, fuente TEXT, descripcion TEXT
                );
                CREATE TABLE IF NOT EXISTS versiones (
                    id SERIAL PRIMARY KEY, dataset_id INT REFERENCES datasets(id),
                    valid_from TIMESTAMP, valid_to TIMESTAMP, hash_contenido TEXT, metadatos JSONB
                );
                CREATE TABLE IF NOT EXISTS registros (
                    id BIGSERIAL PRIMARY KEY, dataset_id INT REFERENCES datasets(id),
                    clave_registro TEXT NOT NULL, hash_fila TEXT NOT NULL, datos JSONB NOT NULL,
                    valid_from TIMESTAMP NOT NULL, valid_to TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_registros_vigencia ON registros (dataset_id, valid_from, valid_to);
            """)
        conn.commit()
    print("Base de datos inicializada correctamente.")