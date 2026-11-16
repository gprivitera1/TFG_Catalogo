from datetime import datetime
from catalogo.db import init_db, get_connection

def poblar():
    init_db()
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Creamos un dataset de prueba
            cur.execute("INSERT INTO datasets (nombre, fuente, descripcion) VALUES ('COVID-19 CCAA', 'Datadista', 'Casos de coronavirus por comunidad autonoma') RETURNING id")
            dataset_id = cur.fetchone()[0]
            
            # 2. Insertamos datos en la versión 1 (Enero 2021)
            cur.execute("""
                INSERT INTO registros (dataset_id, clave_registro, hash_fila, datos, valid_from, valid_to)
                VALUES (%s, 'Madrid', 'hash1', '{"casos": 1000, "fecha": "2021-01-01"}', '2021-01-01', '2021-02-01')
            """, (dataset_id,))
            
            # 3. Insertamos datos en la versión 2 (Febrero 2021)
            cur.execute("""
                INSERT INTO registros (dataset_id, clave_registro, hash_fila, datos, valid_from, valid_to)
                VALUES (%s, 'Madrid', 'hash2', '{"casos": 1500, "fecha": "2021-02-01"}', '2021-02-01', NULL)
            """, (dataset_id,))
            
            # 4. Creamos otro dataset para la búsqueda
            cur.execute("INSERT INTO datasets (nombre, fuente, descripcion) VALUES ('Gasolineras abiertas', 'Ministerio', 'Listado de gasolineras durante el confinamiento')")
            cur.execute("INSERT INTO datasets (nombre, fuente, descripcion) VALUES ('ERTE por provincia', 'Ministerio', 'Expedientes de regulacion temporal de empleo')")
        conn.commit()
    print("Datos de prueba insertados.")

if __name__ == "__main__":
    poblar()