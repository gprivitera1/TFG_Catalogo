import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


import streamlit as st
import pandas as pd
from catalogo.versionado import restaurar_version, obtener_historial_completo
from catalogo.busqueda import buscar_literal, buscar_semantica, indexar_datasets
from catalogo.db import get_connection

try:
    indexar_datasets()
except Exception as e:
    pass # Si la base está vacía, que no rompa la app

st.set_page_config(page_title="Catálogo Inteligente TFG", layout="wide")

st.title("Catálogo inteligente de datasets abiertos")
st.markdown("TFG - Gonzalo Privitera | Búsqueda temporal y semántica")

# --- BARRA LATERAL: BÚSQUEDA ---
st.sidebar.header("Buscador")
query = st.sidebar.text_input("Buscar dataset:", "dónde repostar combustible")
metodo = st.sidebar.radio("Método de búsqueda:", ["Semántica", "Literal"])

if st.sidebar.button("Buscar"):
    if metodo == "Semántica":
        ids_resultados = buscar_semantica(query)
          # --- NUEVO CÓDIGO PARA MOSTRAR NOMBRES ---
        nombres_resultados = []
        if ids_resultados:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for id_ds in ids_resultados:
                        cur.execute("SELECT nombre FROM datasets WHERE id = %s", (id_ds,))
                        fila = cur.fetchone()
                        if fila:
                            nombres_resultados.append(fila[0])
        # -----------------------------------------
        
        if nombres_resultados:
            st.sidebar.success("Encontrados por semántica:")
            for nombre in nombres_resultados:
                st.sidebar.write(f"- {nombre}")
        else:
            st.sidebar.warning("No se encontraron resultados semánticos.")
    else:
        ids_resultados = buscar_literal(query)
        
        nombres_resultados = []
        if ids_resultados:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    for id_ds in ids_resultados:
                        cur.execute("SELECT nombre FROM datasets WHERE id = %s", (id_ds,))
                        fila = cur.fetchone()
                        if fila:
                            nombres_resultados.append(fila[0])
                            
        if nombres_resultados:
            st.sidebar.info("Encontrados por literal:")
            for nombre in nombres_resultados:
                st.sidebar.write(f"- {nombre}")
        else:
            st.sidebar.warning("No se encontraron resultados literales.")

# --- ÁREA PRINCIPAL: RESTAURACIÓN TEMPORAL ---
st.header("Restauración Temporal")
st.markdown("Demostración del guardado histórico con intervalos de validez (`valid_from` y `valid_to`).")

# Simulamos el slider temporal del paper
fecha = st.slider(
    "Fecha de consulta (Año 2021):", 
    min_value=pd.to_datetime('2021-01-01').date(), 
    max_value=pd.to_datetime('2021-12-31').date(), 
    value=pd.to_datetime('2021-02-15').date()
)

if st.button("Restaurar Versión"):
    datos_restaurados = restaurar_version(dataset_id=1, fecha_str=fecha.isoformat())
    
    if datos_restaurados:
        st.success(f"**Datos vigentes en la fecha {fecha}:**")
        
        # Mostramos los datos actuales
        st.dataframe(pd.DataFrame(datos_restaurados), use_container_width=True)
        
        st.markdown("---")
        st.write("### 🔍 Evidencia de Historial y Cambios Estructurales (Auditoría)")
        st.write("El sistema nunca borra datos. Aquí puedes ver todas las versiones guardadas de la Región 'Madrid'. Nota cómo el JSON evoluciona: en abril se añade 'hospitalizados' y en agosto se añade 'uci'.")
        
        # Mostramos todo el historial de Madrid
        historial_madrid = obtener_historial_completo(dataset_id=1, clave_registro='Madrid')
        st.table(historial_madrid)
        
    else:
        st.warning("No hay datos para esta fecha.")