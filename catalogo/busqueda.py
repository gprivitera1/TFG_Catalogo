"""Búsqueda sobre los metadatos del catálogo: literal (línea base), semántica e híbrida (sección V-D)."""
import re
import unicodedata

from .config import DIR_CHROMA
from .db import get_connection
from .embeddings import obtener_embedder

COLECCION = "catalogo"
MAX_COLUMNAS = 30  # los archivos en formato ancho tienen cientos de columnas con fechas

# Palabras vacías del español (se descartan en la búsqueda literal)
PALABRAS_VACIAS = set(
    """a al algo algunas algunos ante antes como con contra cual cuales cuando de del desde donde dónde
    durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos fue
    fueron ha han hasta hay la las le les lo los mas más me mi mis muy no nos o os otra otras otro otros
    para pero por porque que qué quien quienes se sea ser si sí sin sobre su sus también tanto te tiene
    tienen todo todos tu tus u un una unas uno unos y ya cuántos cuántas cuanto cuantos cuánto cuál cada
    según hecho hechas hechos""".split()
)


def texto_indexado(nombre, descripcion, columnas):
    """Título, descripción y primeros 30 nombres de columnas."""
    cols = [c for c in (columnas or "").split(",") if c][:MAX_COLUMNAS]
    partes = [nombre or ""]
    if descripcion:
        partes.append(descripcion)
    if cols:
        partes.append("Columnas: " + ", ".join(cols))
    return ". ".join(partes)


def _cargar_catalogo(conn):
    return conn.execute(
        "SELECT id, nombre, descripcion, columnas, fuente, archivo FROM datasets ORDER BY id"
    ).fetchall()


def _coleccion(crear=False):
    import chromadb

    cliente = chromadb.PersistentClient(path=str(DIR_CHROMA))
    if crear:
        try:
            cliente.delete_collection(COLECCION)
        except Exception:
            pass
        return cliente.create_collection(COLECCION, metadata={"hnsw:space": "cosine"})
    return cliente.get_collection(COLECCION)


def indexar_catalogo():
    """Genera el embedding de cada dataset y lo guarda en ChromaDB (distancia coseno)."""
    with get_connection() as conn:
        filas = _cargar_catalogo(conn)
    if not filas:
        raise RuntimeError("El catálogo está vacío. Ejecute primero scripts/construir_catalogo.py")
    textos = [texto_indexado(n, d, c) for _, n, d, c, _, _ in filas]
    vectores = obtener_embedder().codificar(textos)
    col = _coleccion(crear=True)
    col.add(
        ids=[str(f[0]) for f in filas],
        embeddings=vectores.tolist(),
        documents=textos,
        metadatas=[{"nombre": f[1], "fuente": f[4] or "", "archivo": f[5] or ""} for f in filas],
    )
    return len(filas)


# Compatibilidad con la versión anterior de app.py
indexar_datasets = indexar_catalogo


def buscar_semantica(consulta, k=10):
    """Ids de los k datasets más similares a la consulta (similitud coseno)."""
    vector = obtener_embedder().codificar([consulta])[0]
    res = _coleccion().query(query_embeddings=[vector.tolist()], n_results=k)
    return [int(i) for i in res["ids"][0]]


def _normalizar(texto):
    return unicodedata.normalize("NFC", texto.lower())


def terminos_consulta(consulta):
    """Términos de la consulta sin palabras vacías."""
    palabras = re.findall(r"[\wáéíóúüñ]+", _normalizar(consulta))
    return [p for p in palabras if p not in PALABRAS_VACIAS and len(p) > 1]


def buscar_literal(consulta, k=10, conn=None):
    """Línea base: cada dataset recibe un punto por cada término que aparece (ILIKE)
    en su título, descripción o columnas."""
    terminos = terminos_consulta(consulta)
    if not terminos:
        return []
    puntos = " + ".join(["(CASE WHEN texto ILIKE %s THEN 1 ELSE 0 END)"] * len(terminos))
    sql = f"""
        SELECT id, {puntos} AS puntos FROM (
            SELECT id, coalesce(nombre,'') || ' ' || coalesce(descripcion,'') || ' ' ||
                   coalesce(array_to_string((string_to_array(columnas, ','))[1:{MAX_COLUMNAS}], ' '), '') AS texto
            FROM datasets
        ) t
        WHERE {puntos} > 0
        ORDER BY puntos DESC, id
        LIMIT %s
    """
    params = [f"%{t}%" for t in terminos] * 2 + [k]
    propia = conn is None
    conn = conn or get_connection()
    try:
        return [f[0] for f in conn.execute(sql, params).fetchall()]
    finally:
        if propia:
            conn.close()


def fusion_rrf(rankings, k=10, c=60):
    """Fusión por rango recíproco: puntuación = suma de 1 / (c + posición)."""
    puntos = {}
    for ranking in rankings:
        for pos, i in enumerate(ranking, start=1):
            puntos[i] = puntos.get(i, 0.0) + 1.0 / (c + pos)
    return [i for i, _ in sorted(puntos.items(), key=lambda x: (-x[1], x[0]))][:k]


def buscar_hibrida(consulta, k=10, profundidad=50):
    """Combina los rankings literal y semántico mediante RRF."""
    return fusion_rrf(
        [buscar_literal(consulta, k=profundidad), buscar_semantica(consulta, k=profundidad)], k=k
    )


def nombres_de(ids, conn=None):
    """Nombre y descripción de cada dataset, en el orden recibido."""
    if not ids:
        return []
    propia = conn is None
    conn = conn or get_connection()
    try:
        filas = {
            i: (n, d)
            for i, n, d in conn.execute(
                "SELECT id, nombre, descripcion FROM datasets WHERE id = ANY(%s)", (list(ids),)
            ).fetchall()
        }
        return [(i, *filas[i]) for i in ids if i in filas]
    finally:
        if propia:
            conn.close()
