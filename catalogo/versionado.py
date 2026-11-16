from datetime import datetime
from .db import get_connection
import json

def restaurar_version(dataset_id, fecha_str):
    fecha = datetime.fromisoformat(fecha_str)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT clave_registro, datos, valid_from, valid_to FROM registros 
                WHERE dataset_id = %s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)
            """, (dataset_id, fecha, fecha))
            filas = cur.fetchall()
            
            resultados = []
            for fila in filas:
                resultados.append({
                    "Región": fila[0],
                    "Datos (JSON)": fila[1],
                    "Válido desde": fila[2].strftime('%Y-%m-%d'),
                    "Válido hasta": fila[3].strftime('%Y-%m-%d') if fila[3] else "Actualidad (NULL)"
                })
            return resultados

def obtener_historial_completo(dataset_id, clave_registro):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT datos, valid_from, valid_to FROM registros 
                WHERE dataset_id = %s AND clave_registro = %s ORDER BY valid_from ASC
            """, (dataset_id, clave_registro))
            filas = cur.fetchall()
            return [{"Datos Guardados": f[0], "Desde": f[1].strftime('%Y-%m-%d'), "Hasta": f[2].strftime('%Y-%m-%d') if f[2] else "Actualidad"} for f in filas]