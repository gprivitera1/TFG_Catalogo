"""Versionado incremental, detección de cambios estructurales y restauración por fecha.

Implementa el algoritmo de la sección IV-B:
  1) hash SHA-256 del CSV; si coincide con la última versión, no se registra nada;
  2) perfil de columnas (nombre, posición, tipo inferido, nulos) y comparación con la versión anterior;
  3) comparación de filas por su clave: se cierran (valid_to) las filas eliminadas o modificadas
     y se insertan las nuevas o modificadas con su valid_from;
  4) cierre de la versión anterior y registro de la nueva, sus columnas y sus cambios.
"""
import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date, datetime, timezone

import orjson

from .db import get_connection

# ---------------------------------------------------------------------------
# Lectura del CSV
# ---------------------------------------------------------------------------


def leer_csv(contenido):
    """Devuelve (cabecera, filas) a partir de los bytes de un CSV.

    Elimina la marca BOM (U+FEFF), que algunas versiones incluían una o dos veces y que,
    de otro modo, aparecería como un cambio de nombre de columna. Las filas vacías se ignoran
    y las filas cortas se completan con cadenas vacías.
    """
    if isinstance(contenido, bytes):
        texto = contenido.decode("utf-8", errors="replace")
    else:
        texto = contenido
    lector = csv.reader(io.StringIO(texto, newline=""))
    filas = [f for f in lector if f and any(v != "" for v in f)]
    if not filas:
        return [], []
    cabecera = [c.replace("﻿", "") for c in filas[0]]
    # Nombres de columna repetidos: se numeran para no perder valores.
    vistos = Counter()
    unica = []
    for c in cabecera:
        vistos[c] += 1
        unica.append(c if vistos[c] == 1 else f"{c}_{vistos[c]}")
    n = len(unica)
    datos = []
    for f in filas[1:]:
        if len(f) < n:
            f = f + [""] * (n - len(f))
        elif len(f) > n:
            f = f[:n]
        datos.append(f)
    return unica, datos


# ---------------------------------------------------------------------------
# Perfil de columnas y detección de cambios estructurales
# ---------------------------------------------------------------------------

_RE_ENTERO = re.compile(r"^[+-]?\d+$")
_RE_DECIMAL = re.compile(r"^[+-]?(\d+[.,]\d*|[.,]\d+)([eE][+-]?\d+)?$")
_RE_FECHA = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|\d{4}/\d{1,2}/\d{1,2})$")


def _tipo_valor(v):
    v = v.strip()
    if _RE_ENTERO.match(v):
        return "entero"
    if _RE_DECIMAL.match(v):
        return "decimal"
    if _RE_FECHA.match(v):
        return "fecha"
    return "texto"


def inferir_tipo(valores):
    """Clasifica una columna como entero, decimal, fecha, texto o vacía a partir de sus valores."""
    tipos = {_tipo_valor(v) for v in set(valores) if v.strip() != ""}
    if not tipos:
        return "vacia"
    if tipos == {"entero"}:
        return "entero"
    if tipos <= {"entero", "decimal"}:
        return "decimal"
    if tipos == {"fecha"}:
        return "fecha"
    return "texto"


def perfilar_columnas(cabecera, filas):
    """Lista de columnas con nombre, tipo inferido y cantidad de nulos, en el orden del archivo."""
    perfil = []
    for i, nombre in enumerate(cabecera):
        valores = [f[i] for f in filas]
        perfil.append(
            {
                "nombre": nombre,
                "tipo": inferir_tipo(valores),
                "nulos": sum(1 for v in valores if v.strip() == ""),
            }
        )
    return perfil


def detectar_cambios(anterior, nuevo):
    """Compara dos perfiles de columnas y devuelve la lista de cambios estructurales.

    Tipos de cambio: columna_añadida, columna_eliminada, tipo_modificado y orden_modificado.
    Un renombre aparece como una baja y un alta. Los nulos se registran pero no constituyen
    un cambio estructural; una columna completamente vacía no tiene tipo observable y no
    genera un cambio de tipo.
    """
    if anterior is None:
        return []
    nombres_ant = [c["nombre"] for c in anterior]
    nombres_nue = [c["nombre"] for c in nuevo]
    set_ant, set_nue = set(nombres_ant), set(nombres_nue)
    cambios = []
    for n in nombres_nue:
        if n not in set_ant:
            cambios.append({"tipo": "columna_añadida", "columna": n, "detalle": None})
    for n in nombres_ant:
        if n not in set_nue:
            cambios.append({"tipo": "columna_eliminada", "columna": n, "detalle": None})
    tipos_ant = {c["nombre"]: c["tipo"] for c in anterior}
    for c in nuevo:
        t_ant = tipos_ant.get(c["nombre"])
        if t_ant is None or "vacia" in (t_ant, c["tipo"]):
            continue
        if t_ant != c["tipo"]:
            cambios.append(
                {"tipo": "tipo_modificado", "columna": c["nombre"], "detalle": f"{t_ant} → {c['tipo']}"}
            )
    comunes_ant = [n for n in nombres_ant if n in set_nue]
    comunes_nue = [n for n in nombres_nue if n in set_ant]
    if comunes_ant != comunes_nue:
        cambios.append(
            {
                "tipo": "orden_modificado",
                "columna": None,
                "detalle": ", ".join(comunes_ant) + " → " + ", ".join(comunes_nue),
            }
        )
    return cambios


# ---------------------------------------------------------------------------
# Claves de fila
# ---------------------------------------------------------------------------


def resolver_claves(cabecera, claves):
    """Índices de las columnas clave. Cada clave admite alternativas y la coincidencia ignora mayúsculas."""
    minus = [c.strip().lower() for c in cabecera]
    indices = []
    for alternativas in claves:
        idx = next((minus.index(a.lower()) for a in alternativas if a.lower() in minus), None)
        if idx is None:
            raise ValueError(f"No se encontró la columna clave {alternativas} en {cabecera}")
        indices.append(idx)
    return indices


def claves_de_filas(filas, indices):
    """Clave de cada fila. Las claves duplicadas se numeran por orden de aparición (#2, #3...)."""
    vistos = Counter()
    resultado = []
    for f in filas:
        base = "|".join(f[i] for i in indices)
        vistos[base] += 1
        resultado.append(base if vistos[base] == 1 else f"{base}#{vistos[base]}")
    return resultado


def _hash_fila(datos_json):
    return hashlib.md5(datos_json).hexdigest()


def _a_naive(fecha):
    """Convierte una fecha con zona horaria a UTC sin zona (la columna es TIMESTAMP)."""
    if isinstance(fecha, str):
        fecha = datetime.fromisoformat(fecha)
    if isinstance(fecha, date) and not isinstance(fecha, datetime):
        fecha = datetime(fecha.year, fecha.month, fecha.day, 23, 59, 59)
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


# ---------------------------------------------------------------------------
# Ingesta de una versión
# ---------------------------------------------------------------------------


def registrar_dataset(conn, nombre, fuente, descripcion=None, archivo=None, columnas=None):
    """Crea el dataset si no existe (por archivo) y devuelve su id."""
    if archivo:
        fila = conn.execute("SELECT id FROM datasets WHERE archivo = %s", (archivo,)).fetchone()
        if fila:
            return fila[0]
    return conn.execute(
        "INSERT INTO datasets (nombre, fuente, descripcion, archivo, columnas) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        (nombre, fuente, descripcion, archivo, columnas),
    ).fetchone()[0]


def ingerir(conn, dataset_id, contenido, valid_from, claves, metadatos=None):
    """Registra una versión de un dataset con versionado incremental.

    conn: conexión abierta (la función no hace commit).
    contenido: bytes del CSV.
    valid_from: fecha de publicación de la versión.
    claves: columnas que identifican una fila (lista de listas de alternativas).
    Devuelve un resumen de la versión, o None si el contenido es idéntico al de la última versión.
    """
    valid_from = _a_naive(valid_from)
    hash_contenido = hashlib.sha256(contenido).hexdigest()

    ultima = conn.execute(
        "SELECT id, hash_contenido, valid_from FROM versiones WHERE dataset_id = %s "
        "ORDER BY valid_from DESC LIMIT 1",
        (dataset_id,),
    ).fetchone()
    if ultima and ultima[1] == hash_contenido:
        return None
    if ultima and valid_from <= ultima[2]:
        raise ValueError(f"La versión {valid_from} no es posterior a la última registrada ({ultima[2]})")

    cabecera, filas = leer_csv(contenido)
    perfil = perfilar_columnas(cabecera, filas)

    perfil_anterior = None
    if ultima:
        perfil_anterior = [
            {"nombre": n, "tipo": t, "nulos": nu}
            for n, t, nu in conn.execute(
                "SELECT nombre_columna, tipo_dato, nulos FROM columnas_version WHERE version_id = %s ORDER BY id",
                (ultima[0],),
            ).fetchall()
        ]
    cambios = detectar_cambios(perfil_anterior, perfil)

    # Filas de la nueva versión: clave -> (hash, json)
    indices = resolver_claves(cabecera, claves)
    claves_filas = claves_de_filas(filas, indices)
    nuevas = {}
    for clave, f in zip(claves_filas, filas):
        # Claves ordenadas: el hash no cambia si solo se reordenan las columnas
        datos_json = orjson.dumps(dict(zip(cabecera, f)), option=orjson.OPT_SORT_KEYS)
        nuevas[clave] = (_hash_fila(datos_json), datos_json)

    # Filas vigentes de la versión anterior (índice parcial valid_to IS NULL)
    actuales = {
        clave: (h, rid)
        for rid, clave, h in conn.execute(
            "SELECT id, clave_registro, hash_fila FROM registros WHERE dataset_id = %s AND valid_to IS NULL",
            (dataset_id,),
        ).fetchall()
    }

    a_cerrar = []
    eliminadas = modificadas = 0
    for clave, (h, rid) in actuales.items():
        nueva = nuevas.get(clave)
        if nueva is None:
            a_cerrar.append(rid)
            eliminadas += 1
        elif nueva[0] != h:
            a_cerrar.append(rid)
            modificadas += 1
    a_insertar = [
        (clave, h, j) for clave, (h, j) in nuevas.items() if clave not in actuales or actuales[clave][0] != h
    ]
    añadidas = sum(1 for clave in nuevas if clave not in actuales)

    if a_cerrar:
        conn.execute(
            "UPDATE registros SET valid_to = %s WHERE id = ANY(%s)", (valid_from, a_cerrar)
        )
    if a_insertar:
        with conn.cursor() as cur:
            with cur.copy(
                "COPY registros (dataset_id, clave_registro, hash_fila, datos, valid_from) FROM STDIN"
            ) as copy:
                for clave, h, j in a_insertar:
                    copy.write_row((dataset_id, clave, h, j.decode("utf-8"), valid_from))

    if ultima:
        conn.execute("UPDATE versiones SET valid_to = %s WHERE id = %s", (valid_from, ultima[0]))

    meta = dict(metadatos or {})
    meta.update(
        {
            "filas": len(filas),
            "claves": [cabecera[i] for i in indices],
            "filas_añadidas": añadidas,
            "filas_eliminadas": eliminadas,
            "filas_modificadas": modificadas,
            "filas_insertadas": len(a_insertar),
            "filas_cerradas": len(a_cerrar),
        }
    )
    version_id = conn.execute(
        "INSERT INTO versiones (dataset_id, valid_from, hash_contenido, metadatos) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (dataset_id, valid_from, hash_contenido, orjson.dumps(meta).decode()),
    ).fetchone()[0]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO columnas_version (version_id, nombre_columna, tipo_dato, nulos) VALUES (%s,%s,%s,%s)",
            [(version_id, c["nombre"], c["tipo"], c["nulos"]) for c in perfil],
        )
        if cambios:
            cur.executemany(
                "INSERT INTO cambios (version_id, tipo, columna, detalle) VALUES (%s,%s,%s,%s)",
                [(version_id, c["tipo"], c["columna"], c["detalle"]) for c in cambios],
            )
    return {"version_id": version_id, "valid_from": valid_from, "cambios": cambios, **meta}


# ---------------------------------------------------------------------------
# Restauración (Listado 2)
# ---------------------------------------------------------------------------

SQL_RESTAURAR = (
    "SELECT datos{cast} FROM registros "
    "WHERE dataset_id = %s AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)"
)


def restaurar_version(dataset_id, fecha_str=None, optimizada=True, conn=None, fecha=None):
    """Devuelve las filas (lista de diccionarios) vigentes en una fecha.

    optimizada=True solicita el JSONB como texto y lo decodifica con orjson;
    optimizada=False deja que el controlador convierta cada valor en un diccionario
    (implementación inicial, conservada para compararlas; sección V-C).
    """
    fecha = _a_naive(fecha if fecha is not None else fecha_str)
    propia = conn is None
    conn = conn or get_connection()
    try:
        if optimizada:
            filas = conn.execute(SQL_RESTAURAR.format(cast="::text"), (dataset_id, fecha, fecha)).fetchall()
            return [orjson.loads(f[0]) for f in filas]
        filas = conn.execute(SQL_RESTAURAR.format(cast=""), (dataset_id, fecha, fecha)).fetchall()
        return [f[0] for f in filas]
    finally:
        if propia:
            conn.close()


def listar_datasets_versionados(conn=None):
    """Datasets que tienen al menos una versión: (id, nombre, cantidad de versiones)."""
    propia = conn is None
    conn = conn or get_connection()
    try:
        return conn.execute(
            "SELECT d.id, d.nombre, count(v.id) FROM datasets d JOIN versiones v ON v.dataset_id = d.id "
            "GROUP BY d.id, d.nombre ORDER BY d.id"
        ).fetchall()
    finally:
        if propia:
            conn.close()


def listar_versiones(dataset_id, conn=None):
    """Versiones de un dataset ordenadas por fecha: lista de diccionarios."""
    propia = conn is None
    conn = conn or get_connection()
    try:
        filas = conn.execute(
            "SELECT id, valid_from, valid_to, hash_contenido, metadatos FROM versiones "
            "WHERE dataset_id = %s ORDER BY valid_from",
            (dataset_id,),
        ).fetchall()
        return [
            {"id": i, "valid_from": vf, "valid_to": vt, "hash": h, "metadatos": m}
            for i, vf, vt, h, m in filas
        ]
    finally:
        if propia:
            conn.close()


def columnas_de_version(version_id, conn=None):
    propia = conn is None
    conn = conn or get_connection()
    try:
        return [
            {"nombre": n, "tipo": t, "nulos": nu}
            for n, t, nu in conn.execute(
                "SELECT nombre_columna, tipo_dato, nulos FROM columnas_version WHERE version_id = %s ORDER BY id",
                (version_id,),
            ).fetchall()
        ]
    finally:
        if propia:
            conn.close()


def cambios_de_version(version_id, conn=None):
    propia = conn is None
    conn = conn or get_connection()
    try:
        return [
            {"tipo": t, "columna": c, "detalle": d}
            for t, c, d in conn.execute(
                "SELECT tipo, columna, detalle FROM cambios WHERE version_id = %s ORDER BY id", (version_id,)
            ).fetchall()
        ]
    finally:
        if propia:
            conn.close()


def obtener_historial_completo(dataset_id, clave_registro, conn=None):
    """Todas las versiones guardadas de una fila, con su intervalo de validez."""
    propia = conn is None
    conn = conn or get_connection()
    try:
        filas = conn.execute(
            "SELECT valid_from, valid_to, datos::text FROM registros "
            "WHERE dataset_id = %s AND clave_registro = %s ORDER BY valid_from",
            (dataset_id, clave_registro),
        ).fetchall()
        return [{"valid_from": vf, "valid_to": vt, **orjson.loads(d)} for vf, vt, d in filas]
    finally:
        if propia:
            conn.close()
