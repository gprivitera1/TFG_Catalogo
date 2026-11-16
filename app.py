"""Interfaz web del prototipo (sección V-E, Fig. 2).

Uso:  streamlit run app.py
"""
import os
import sys
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from catalogo.busqueda import buscar_literal, buscar_semantica, nombres_de  # noqa: E402
from catalogo.config import SERIES  # noqa: E402
from catalogo.db import get_connection  # noqa: E402
from catalogo.embeddings import obtener_embedder  # noqa: E402
from catalogo.versionado import (  # noqa: E402
    cambios_de_version,
    columnas_de_version,
    listar_versiones,
    restaurar_version,
)

st.set_page_config(page_title="Catálogo inteligente de datasets abiertos", layout="wide")

NOMBRE_SERIE = {cfg["archivo"]: cfg["nombre"] for cfg in SERIES.values()}
COLORES = {
    "columna_añadida": ("#1b7f3b", "#e3f4e8", "Añadida"),
    "columna_eliminada": ("#b42318", "#fde8e6", "Eliminada"),
    "tipo_modificado": ("#b54708", "#fff1e0", "Tipo modificado"),
    "orden_modificado": ("#b54708", "#fff1e0", "Orden modificado"),
}


@st.cache_resource(show_spinner="Cargando el modelo de embeddings...")
def _modelo():
    return obtener_embedder()


@st.cache_data(ttl=600)
def _datasets_versionados():
    with get_connection() as conn:
        return conn.execute(
            "SELECT d.id, d.archivo, d.nombre, count(v.id) FROM datasets d JOIN versiones v ON v.dataset_id = d.id "
            "WHERE d.archivo NOT LIKE 'sintetico/%%' GROUP BY d.id ORDER BY d.id"
        ).fetchall()


@st.cache_data(ttl=600)
def _versiones(dataset_id):
    return listar_versiones(dataset_id)


# --------------------------------------------------------------------------
# Barra lateral: buscador
# --------------------------------------------------------------------------
st.sidebar.header("Buscador")
consulta = st.sidebar.text_input("Buscar dataset", placeholder="Ej.: dónde repostar combustible durante el confinamiento")
metodo = st.sidebar.radio("Método de búsqueda", ["Semántico", "Literal"], horizontal=True)

if consulta:
    if metodo == "Semántico":
        _modelo()
        ids = buscar_semantica(consulta, k=10)
    else:
        ids = buscar_literal(consulta, k=10)
    resultados = nombres_de(ids)
    if resultados:
        st.sidebar.caption(f"{len(resultados)} resultados ({metodo.lower()})")
        for pos, (_, nombre, desc) in enumerate(resultados, start=1):
            st.sidebar.markdown(f"**{pos}. {nombre}**")
            if desc:
                st.sidebar.caption(desc[:180] + ("…" if len(desc) > 180 else ""))
    else:
        st.sidebar.warning("La búsqueda no devolvió resultados.")

# --------------------------------------------------------------------------
# Área principal: navegación temporal
# --------------------------------------------------------------------------
st.title("Catálogo inteligente de datasets abiertos")
st.caption("Trazabilidad temporal con intervalos de validez (valid_from, valid_to) y búsqueda semántica")

datasets = _datasets_versionados()
if not datasets:
    st.warning("No hay datasets versionados. Ejecute scripts/cargar_historial.py.")
    st.stop()

opciones = {d[0]: f"{NOMBRE_SERIE.get(d[1], d[2])} ({d[3]} versiones)" for d in datasets}
dataset_id = st.selectbox("Dataset versionado", list(opciones), format_func=opciones.get)
versiones = _versiones(dataset_id)
col_fecha, _ = st.columns([1, 3])
fecha_elegida = col_fecha.date_input(
    "Ir a una fecha",
    value=None,
    min_value=versiones[0]["valid_from"].date(),
    max_value=versiones[-1]["valid_from"].date(),
    format="DD/MM/YYYY",
    key=f"fecha_{dataset_id}",
)
if fecha_elegida is None:
    inicial = len(versiones) - 1
else:
    # Versión vigente al final del día elegido
    limite = datetime.combine(fecha_elegida, time(23, 59, 59))
    vigentes = [i for i, v in enumerate(versiones) if v["valid_from"] <= limite]
    inicial = vigentes[-1] if vigentes else 0

indice = st.select_slider(
    "Versión publicada",
    options=list(range(len(versiones))),
    value=inicial,
    key=f"version_{dataset_id}_{fecha_elegida}",
    format_func=lambda i: versiones[i]["valid_from"].strftime("%d/%m/%Y %H:%M"),
)
version = versiones[indice]
meta = version["metadatos"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Filas de la versión", f"{meta['filas']:,}".replace(",", "."))
c2.metric("Filas añadidas", f"{meta['filas_añadidas']:,}".replace(",", "."))
c3.metric("Filas eliminadas", f"{meta['filas_eliminadas']:,}".replace(",", "."))
c4.metric("Filas modificadas", f"{meta['filas_modificadas']:,}".replace(",", "."))

st.subheader("Cambios respecto de la versión anterior")
cambios = cambios_de_version(version["id"])
if indice == 0:
    st.info("Primera versión registrada.")
elif not cambios:
    st.caption("Sin cambios estructurales: solo cambiaron los datos.")
else:
    etiquetas = []
    for c in cambios:
        color, fondo, texto = COLORES[c["tipo"]]
        nombre = c["columna"] if c["columna"] is not None else ""
        detalle = f" ({c['detalle']})" if c["tipo"] == "tipo_modificado" else ""
        etiquetas.append(
            f"<span style='background:{fondo};color:{color};border:1px solid {color};border-radius:6px;"
            f"padding:3px 8px;margin:2px;display:inline-block;font-size:0.9em'>"
            f"<b>{texto}</b> {nombre}{detalle}</span>"
        )
    st.markdown(" ".join(etiquetas), unsafe_allow_html=True)
    orden = [c for c in cambios if c["tipo"] == "orden_modificado"]
    for c in orden:
        st.caption(f"Orden de columnas: {c['detalle']}")

st.subheader(f"Datos vigentes el {version['valid_from']:%d/%m/%Y %H:%M}")
filas = restaurar_version(dataset_id, fecha=version["valid_from"])
columnas = [c["nombre"] for c in columnas_de_version(version["id"])]
df = pd.DataFrame(filas, columns=columnas)
claves = [c for c in meta.get("claves", []) if c in df.columns]
if claves:
    df = df.sort_values(claves, kind="stable").reset_index(drop=True)
st.dataframe(df, use_container_width=True, height=420)
st.caption(
    f"Versión {indice + 1} de {len(versiones)} · hash SHA-256 {version['hash'][:16]}… · "
    f"publicada en el commit {meta.get('commit', '')[:10]} del repositorio de Datadista"
)
