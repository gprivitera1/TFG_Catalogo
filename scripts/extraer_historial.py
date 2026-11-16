"""Extrae del repositorio git de Datadista cada versión publicada de las cuatro series de COVID-19
y los 79 CSV que forman el catálogo de prueba (secciones V-A y V-D).

Uso:  python scripts/extraer_historial.py

Requiere git instalado. Clona el repositorio sin descargar el contenido de todos los archivos
(--filter=blob:none) y luego descarga solo los archivos necesarios.
"""
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import (  # noqa: E402
    DIR_CATALOGO,
    DIR_HISTORIAL,
    DIR_REPO_DATADISTA,
    SERIES,
    URL_DATADISTA,
)


def git(*args, binario=False):
    res = subprocess.run(
        ["git", "-C", str(DIR_REPO_DATADISTA), *args], capture_output=True, check=True
    )
    return res.stdout if binario else res.stdout.decode("utf-8")


def clonar():
    if (DIR_REPO_DATADISTA / ".git").exists():
        print("Repositorio de Datadista ya clonado; se actualiza.")
        subprocess.run(["git", "-C", str(DIR_REPO_DATADISTA), "fetch", "-q", "origin"], check=True)
        return
    DIR_REPO_DATADISTA.parent.mkdir(parents=True, exist_ok=True)
    print("Clonando el repositorio de Datadista (sin contenidos)...")
    subprocess.run(
        ["git", "clone", "-q", "--filter=blob:none", "--no-checkout", URL_DATADISTA, str(DIR_REPO_DATADISTA)],
        check=True,
    )


def descargar_blobs(oids):
    """Descarga en bloque el contenido de los archivos (clon parcial)."""
    faltan = git("cat-file", "--batch-check", "--batch-all-objects")  # objetos locales
    locales = {l.split()[0] for l in faltan.splitlines() if l}
    pendientes = sorted(set(oids) - locales)
    for i in range(0, len(pendientes), 400):
        subprocess.run(
            ["git", "-C", str(DIR_REPO_DATADISTA), "fetch", "-q", "origin", "--no-tags",
             "--no-write-fetch-head", *pendientes[i : i + 400]],
            check=True,
        )


def historial_de(archivo):
    """Lista (commit, fecha ISO, ruta) de cada commit que modificó el archivo, siguiendo renombres."""
    salida = git("log", "--follow", "--name-only", "--format=@@%H %cI", "--", archivo)
    resultado, actual = [], None
    for linea in salida.splitlines():
        if linea.startswith("@@"):
            actual = linea[2:].split(" ")
        elif linea.strip():
            resultado.append((actual[0], actual[1], linea))
    resultado.reverse()  # del más antiguo al más reciente
    return resultado


def main():
    clonar()
    head = git("rev-parse", "origin/HEAD" if "origin/HEAD" in git("branch", "-r") else "origin/master").strip()

    # 1) Historial de las cuatro series
    entradas = []
    for serie, cfg in SERIES.items():
        for commit, fecha, ruta in historial_de(cfg["archivo"]):
            oid = git("rev-parse", f"{commit}:{ruta}").strip()
            entradas.append({"serie": serie, "commit": commit, "fecha": fecha, "ruta": ruta, "oid": oid})

    # 2) Los CSV del catálogo (versión actual del repositorio) y las fichas README
    arbol = git("ls-tree", "-r", "-z", head).split("\0")
    catalogo = []
    for linea in arbol:
        if not linea:
            continue
        info, ruta = linea.split("\t", 1)
        _, tipo, oid = info.split()
        if ruta.lower().endswith(".csv") or ruta.lower().endswith("readme.md"):
            catalogo.append({"ruta": ruta, "oid": oid})

    print(f"Descargando {len({e['oid'] for e in entradas} | {c['oid'] for c in catalogo})} archivos...")
    descargar_blobs([e["oid"] for e in entradas] + [c["oid"] for c in catalogo])

    # Escritura del historial
    if DIR_HISTORIAL.exists():
        shutil.rmtree(DIR_HISTORIAL)
    manifiesto = []
    for serie in SERIES:
        n = 0
        for e in [x for x in entradas if x["serie"] == serie]:
            n += 1
            fecha = datetime.fromisoformat(e["fecha"]).astimezone(timezone.utc)
            destino = DIR_HISTORIAL / serie / f"{n:04d}_{fecha:%Y%m%dT%H%M%S}.csv"
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(git("cat-file", "-p", e["oid"], binario=True))
            manifiesto.append({**e, "archivo_local": str(destino.relative_to(DIR_HISTORIAL))})
        print(f"  {serie}: {n} archivos")
    (DIR_HISTORIAL / "manifiesto.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # Escritura del catálogo
    if DIR_CATALOGO.exists():
        shutil.rmtree(DIR_CATALOGO)
    n_csv = 0
    for c in catalogo:
        destino = DIR_CATALOGO / c["ruta"]
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(git("cat-file", "-p", c["oid"], binario=True))
        n_csv += c["ruta"].lower().endswith(".csv")
    print(f"Historial: {len(manifiesto)} archivos en {DIR_HISTORIAL}")
    print(f"Catálogo: {n_csv} archivos CSV en {DIR_CATALOGO}")


if __name__ == "__main__":
    main()
