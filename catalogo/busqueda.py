import chromadb
from .db import get_connection

# Inicializamos ChromaDB en memoria para la demo
chroma_client = chromadb.Client()
coleccion = chroma_client.get_or_create_collection(name="datasets")

def indexar_datasets():
    """Toma los datasets de Postgres y los indexa en ChromaDB"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre, descripcion FROM datasets")
            for row in cur.fetchall():
                texto = f"{row[1]} {row[2]}"
                coleccion.add(documents=[texto], metadatas=[{"id": row[0]}], ids=[str(row[0])])

def buscar_semantica(query, n=5):
    resultados = coleccion.query(query_texts=[query], n_results=n)
    return [meta["id"] for meta in resultados['metadatas'][0]]

def buscar_literal(query, n=5):
    """Búsqueda literal con ILIKE en Postgres (Línea base del TFG)"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Simplificación de la búsqueda literal para la demo
            cur.execute("""
                SELECT id FROM datasets 
                WHERE nombre ILIKE %s OR descripcion ILIKE %s LIMIT %s
            """, (f"%{query}%", f"%{query}%", n))
            return [row[0] for row in cur.fetchall()]