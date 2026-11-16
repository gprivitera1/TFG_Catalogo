"""Construye el catálogo de prueba con los CSV del repositorio de Datadista y lo indexa en ChromaDB
(sección V-D).

Para cada archivo se registra un título derivado del nombre del archivo, la descripción tomada de su
ficha en el README del repositorio (cuando existe) y los nombres de sus columnas.

Uso:  python scripts/construir_catalogo.py
"""
import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.busqueda import indexar_catalogo  # noqa: E402
from catalogo.config import DIR_CATALOGO, titulo_desde_archivo  # noqa: E402
from catalogo.db import get_connection, init_db  # noqa: E402

_RE_ARCHIVO = re.compile(r"\[([^\]\s]+\.csv)\]", re.IGNORECASE)
_RE_DESC = re.compile(r"^\s*\**\s*Descripci[oó]n\s*\**\s*:\s*\**\s*(.*)$", re.IGNORECASE)


def _limpiar(texto):
    texto = re.sub(r"<br\s*/?>", " ", texto)
    texto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", texto)  # enlaces markdown
    texto = texto.replace("**", "").replace("*", "")
    return re.sub(r"\s+", " ", texto).strip(" .") + "."


def descripciones_readme(rutas_readme):
    """Asocia cada nombre de archivo CSV con la descripción de su ficha en el README.

    En el README de Datadista las fichas están separadas por la marca <br><br>. Todos los archivos
    nombrados en una ficha (formato ancho, formato largo, archivo original) reciben la descripción
    de esa ficha, tomada de su línea "Descripción:".
    """
    resultado = {}
    for ruta in rutas_readme:
        fichas, actual = [], []
        for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
            if "<br><br>" in linea or linea.lstrip().startswith("#"):
                fichas.append(actual)
                actual = []
            if not linea.lstrip().startswith("|"):
                actual.append(linea)
        fichas.append(actual)
        for ficha in fichas:
            archivos = [Path(m).name for l in ficha if "archivo" in l.lower() for m in _RE_ARCHIVO.findall(l)]
            descs = [m.group(1) for l in ficha if (m := _RE_DESC.match(l)) and m.group(1).strip()]
            if archivos and descs:
                for a in archivos:
                    resultado.setdefault(a, _limpiar(descs[0]))
    return resultado


def descripcion_de(nombre_archivo, descs):
    """Descripción de un archivo. Según el README, los archivos con la nomenclatura "old" son la
    versión antigua (hasta el 30-04-2020) del mismo dataset, por lo que heredan su descripción."""
    if nombre_archivo in descs:
        return descs[nombre_archivo]
    if nombre_archivo.endswith("_old.csv"):
        return descs.get(nombre_archivo[: -len("_old.csv")] + ".csv")
    return None


def columnas_csv(ruta):
    with open(ruta, "rb") as f:
        primera = f.readline().decode("utf-8", errors="replace").replace("﻿", "")
    try:
        return next(csv.reader(io.StringIO(primera)))
    except StopIteration:
        return []


def main():
    if not DIR_CATALOGO.exists():
        sys.exit("No se encontró el catálogo. Ejecute primero: python scripts/extraer_historial.py")
    init_db()
    csvs = sorted(p for p in DIR_CATALOGO.rglob("*") if p.suffix.lower() == ".csv")
    readmes = sorted(p for p in DIR_CATALOGO.rglob("*") if p.name.lower() == "readme.md")
    descs = descripciones_readme(readmes)

    con_desc = 0
    with get_connection() as conn:
        for p in csvs:
            archivo = p.relative_to(DIR_CATALOGO).as_posix()
            desc = descripcion_de(p.name, descs)
            con_desc += desc is not None
            cols = ",".join(c.strip() for c in columnas_csv(p))
            existe = conn.execute("SELECT id FROM datasets WHERE archivo = %s", (archivo,)).fetchone()
            valores = (titulo_desde_archivo(archivo), "Datadista", desc, cols)
            if existe:
                conn.execute(
                    "UPDATE datasets SET nombre=%s, fuente=%s, descripcion=%s, columnas=%s WHERE id=%s",
                    (*valores, existe[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO datasets (nombre, fuente, descripcion, columnas, archivo) VALUES (%s,%s,%s,%s,%s)",
                    (*valores, archivo),
                )
        conn.commit()
    print(f"Catálogo: {len(csvs)} datasets; {con_desc} con descripción del README y "
          f"{len(csvs) - con_desc} solo con título y columnas.")
    n = indexar_catalogo()
    print(f"Indexados en ChromaDB: {n} datasets.")


if __name__ == "__main__":
    main()
