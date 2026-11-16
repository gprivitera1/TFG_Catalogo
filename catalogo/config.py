"""Configuración común del prototipo: rutas, conexión y series versionadas."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env():
    """Lee el archivo .env de la raíz del proyecto (formato CLAVE=valor)."""
    ruta = RAIZ / ".env"
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip())


_cargar_env()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://tfg_user:root@localhost:5432/catalogo_tfg"
)

DIR_DATASETS = RAIZ / "datasets"
DIR_REPO_DATADISTA = DIR_DATASETS / "datadista"
DIR_HISTORIAL = DIR_DATASETS / "historial"
DIR_CATALOGO = DIR_DATASETS / "catalogo"
DIR_MODELO = RAIZ / "modelos" / "all-MiniLM-L6-v2"
DIR_CHROMA = RAIZ / "chroma"
DIR_RESULTADOS = RAIZ / "resultados"
DIR_EVAL = RAIZ / "eval"

URL_DATADISTA = "https://github.com/datadista/datasets"

def titulo_desde_archivo(ruta):
    """Título de un dataset derivado del nombre de su archivo."""
    nombre = Path(ruta).stem
    return nombre.replace("_", " ").replace("-", " ").strip()


# Series de COVID-19 cuyo historial se versiona (sección V-A).
# "claves": columnas que identifican una fila. Cada elemento es una lista de
# alternativas, porque los nombres cambiaron a lo largo del historial; la
# coincidencia ignora mayúsculas.
SERIES = {
    "nacional": {
        "nombre": "COVID-19: serie nacional",
        "archivo": "COVID 19/nacional_covid19.csv",
        "claves": [["fecha"]],
    },
    "ccaa_nueva": {
        "nombre": "COVID-19: casos por comunidad autónoma (ISCIII, serie nueva)",
        "archivo": "COVID 19/ccaa_covid19_datos_isciii_nueva_serie.csv",
        "claves": [["fecha"], ["cod_ine", "ccaa_iso"]],
    },
    "provincias": {
        "nombre": "COVID-19: casos por provincia (ISCIII)",
        "archivo": "COVID 19/provincias_covid19_datos_isciii_nueva_serie.csv",
        "claves": [["fecha"], ["cod_ine", "provincia_iso"]],
    },
    "ccaa_antigua": {
        "nombre": "COVID-19: datos por comunidad autónoma (ISCIII, serie antigua)",
        "archivo": "COVID 19/old_series/ccaa_covid19_datos_isciii.csv",
        "claves": [["fecha"], ["cod_ine"]],
    },
}
