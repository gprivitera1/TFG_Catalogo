# Catálogo inteligente de datasets abiertos con trazabilidad temporal y búsqueda semántica

Prototipo del Trabajo Final de Grado de Gonzalo Privitera (Licenciatura en Tecnologías de la Información,
Universidad de Palermo, 2026). Tutor: Gonzalo Javier Diaz.

Repositorio: https://github.com/gprivitera1/TFG_Catalogo

El sistema versiona de forma incremental el historial real de cuatro series de COVID-19 de España
(1.067 versiones publicadas entre 2020 y 2022), permite restaurar cualquier versión pasada por fecha,
detecta los cambios estructurales entre versiones y ofrece búsqueda literal, semántica e híbrida
sobre un catálogo de 79 datasets.

## Estructura

```
catalogo/                 paquete principal
  config.py               rutas, conexión y series versionadas
  db.py                   conexión y esquema de la base de datos (Listado 1)
  versionado.py           versionado incremental, detección de cambios y restauración (Listado 2)
  embeddings.py           all-MiniLM-L6-v2 con ONNX Runtime (mean pooling y normalización L2)
  busqueda.py             búsqueda literal, semántica (ChromaDB) e híbrida (RRF)
app.py                    interfaz web (Streamlit)
scripts/
  extraer_historial.py    extrae del repositorio git de Datadista cada versión de las series y los 79 CSV
  cargar_historial.py     carga el historial en PostgreSQL con versionado incremental
  construir_catalogo.py   registra los 79 datasets del catálogo y los indexa en ChromaDB
  descargar_modelo.py     descarga el modelo ONNX y verifica su hash SHA-256
  exp_volumen.py          Tabla II, exactitud de la restauración, espacio en disco y Fig. 3
  exp_deteccion.py        Tablas III y IV (historial real y prueba controlada)
  exp_restauracion.py     Tabla V y Fig. 4 (incluye los datasets sintéticos)
  exp_busqueda.py         Tablas VI y VII y Fig. 5 (requiere eval/consultas.json anotado)
  exp_interfaz.py         Tabla VIII (Playwright)
eval/consultas.json       100 consultas de prueba y juicios de relevancia (Anexo A)
resultados/               resultados de los experimentos en JSON
```

Los datos no se incluyen en el repositorio: se obtienen del repositorio público de Datadista
(https://github.com/datadista/datasets) con `scripts/extraer_historial.py`.

## Requisitos

- Python 3.11 o superior (probado con 3.13)
- PostgreSQL 16
- git

## Instalación

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Crear la base de datos (en psql, como usuario administrador):

```sql
CREATE USER tfg_user PASSWORD 'una_contraseña';
CREATE DATABASE catalogo_tfg OWNER tfg_user;
```

Copiar `.env.example` como `.env` y completar la contraseña.

Configuración de PostgreSQL usada en las mediciones (postgresql.conf): `shared_buffers = 512MB`,
`work_mem = 64MB`.

## Carga de los datos (una sola vez, unos 5 minutos)

```bash
python scripts/descargar_modelo.py        # modelo all-MiniLM-L6-v2 (ONNX, ~90 MB)
python scripts/extraer_historial.py       # 1.069 archivos de historial + 79 CSV del catálogo (~220 MB)
python scripts/cargar_historial.py        # 1.067 versiones (2 descartadas por hash idéntico)
python scripts/construir_catalogo.py      # 79 datasets indexados en ChromaDB
```

## Interfaz

```bash
streamlit run app.py
```

Se abre en http://localhost:8501. En el panel lateral está el buscador (semántico o literal); en el
área principal se elige un dataset versionado y se recorren sus versiones con el slider: para cada
fecha se muestra la tabla restaurada y los cambios respecto de la versión anterior (columnas añadidas
en verde, eliminadas en rojo y modificadas en naranja, con la cantidad de filas añadidas, eliminadas
y modificadas).

## Experimentos

```bash
python scripts/exp_volumen.py
python scripts/exp_deteccion.py
python scripts/exp_restauracion.py
python scripts/exp_busqueda.py            # requiere los juicios de relevancia en eval/consultas.json
python scripts/exp_interfaz.py            # con la interfaz en ejecución; requiere playwright
```

Cada script guarda sus resultados en `resultados/`.
