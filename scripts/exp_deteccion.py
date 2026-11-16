"""Evaluación de la detección de cambios estructurales (secciones VI-A y VII-C: Tablas III y IV).

1) Historial real: compara los cambios registrados por el módulo con un registro de referencia
   elaborado de forma independiente, leyendo directamente la cabecera de cada versión.
2) Prueba controlada: sobre 30 versiones reales elegidas al azar se inyectan cambios conocidos
   (150 ensayos por tipo), con controles negativos. Se ensaya aparte el cambio de formato de fecha.

Uso:  python scripts/exp_deteccion.py
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_HISTORIAL, DIR_RESULTADOS, SERIES  # noqa: E402
from catalogo.db import get_connection  # noqa: E402
from catalogo.versionado import detectar_cambios, leer_csv, perfilar_columnas  # noqa: E402

SEMILLA = 2026
ENSAYOS = 150
VERSIONES_BASE = 30


# ---------------------------------------------------------------------------
# 1) Historial real
# ---------------------------------------------------------------------------

def cabecera_directa(ruta):
    """Registro de referencia: lee solo la primera línea del archivo, sin usar el módulo."""
    with open(ruta, "rb") as f:
        linea = f.readline().decode("utf-8", errors="replace")
    return [c.replace("﻿", "") for c in linea.rstrip("\r\n").split(",")]


def evaluar_historial():
    manifiesto = json.loads((DIR_HISTORIAL / "manifiesto.json").read_text(encoding="utf-8"))
    referencia = Counter()
    with get_connection() as conn:
        for serie, cfg in SERIES.items():
            did = conn.execute("SELECT id FROM datasets WHERE archivo = %s", (cfg["archivo"],)).fetchone()[0]
            commits = {
                r[0]
                for r in conn.execute("SELECT metadatos->>'commit' FROM versiones WHERE dataset_id = %s", (did,))
            }
            entradas = [m for m in manifiesto if m["serie"] == serie and m["commit"] in commits]
            anterior = None
            for m in entradas:
                cab = cabecera_directa(DIR_HISTORIAL / m["archivo_local"])
                if anterior is not None:
                    for c in cab:
                        if c not in anterior:
                            referencia[(cfg["archivo"], m["commit"], "columna_añadida", c)] += 1
                    for c in anterior:
                        if c not in cab:
                            referencia[(cfg["archivo"], m["commit"], "columna_eliminada", c)] += 1
                    comunes_a = [c for c in anterior if c in cab]
                    comunes_n = [c for c in cab if c in anterior]
                    if comunes_a != comunes_n:
                        referencia[(cfg["archivo"], m["commit"], "orden_modificado", None)] += 1
                anterior = cab
        detectados = Counter()
        tipos = []
        for commit, fecha, archivo, tipo, columna, detalle in conn.execute(
            "SELECT v.metadatos->>'commit', v.valid_from, d.archivo, c.tipo, c.columna, c.detalle "
            "FROM cambios c JOIN versiones v ON v.id = c.version_id JOIN datasets d ON d.id = v.dataset_id "
            "ORDER BY v.valid_from"
        ):
            if tipo == "tipo_modificado":
                tipos.append({"fecha": fecha.isoformat(), "archivo": archivo, "columna": columna, "detalle": detalle})
            else:
                detectados[(archivo, commit, tipo, columna)] += 1
    aciertos = sum((referencia & detectados).values())
    return {
        "cambios_referencia": sum(referencia.values()),
        "transiciones_con_cambios": len({k[:2] for k in referencia}),
        "detectados_correctamente": aciertos,
        "no_detectados": sum((referencia - detectados).values()),
        "falsos_positivos": sum((detectados - referencia).values()),
        "cambios_de_tipo_detectados": tipos,
    }


# ---------------------------------------------------------------------------
# 2) Prueba controlada
# ---------------------------------------------------------------------------

def _columnas_de_tipo(perfil, tipos):
    return [i for i, c in enumerate(perfil) if c["tipo"] in tipos]


def inyectar(tipo, cab, filas, perfil, rnd):
    """Devuelve (cabecera, filas, cambios esperados) para un tipo de cambio inyectado."""
    cab = list(cab)
    filas = [list(f) for f in filas]
    if tipo == "Columna añadida":
        nombre = f"columna_nueva_{rnd.randint(1, 10**6)}"
        pos = rnd.randint(0, len(cab))
        cab.insert(pos, nombre)
        for f in filas:
            f.insert(pos, str(rnd.randint(0, 1000)))
        return cab, filas, [("columna_añadida", nombre)]
    if tipo == "Columna eliminada":
        pos = rnd.randrange(len(cab))
        nombre = cab.pop(pos)
        for f in filas:
            f.pop(pos)
        return cab, filas, [("columna_eliminada", nombre)]
    if tipo == "Columna renombrada":
        pos = rnd.randrange(len(cab))
        viejo = cab[pos]
        cab[pos] = viejo + "_renombrada"
        return cab, filas, [("columna_añadida", cab[pos]), ("columna_eliminada", viejo)]
    if tipo == "Tipo modificado":
        pos = rnd.choice(_columnas_de_tipo(perfil, {"entero", "decimal", "fecha"}))
        for f in filas:
            if f[pos].strip():
                f[pos] = "v" + f[pos]
        return cab, filas, [("tipo_modificado", cab[pos])]
    if tipo == "Orden modificado":
        pos = rnd.randrange(len(cab) - 1)
        cab[pos], cab[pos + 1] = cab[pos + 1], cab[pos]
        for f in filas:
            f[pos], f[pos + 1] = f[pos + 1], f[pos]
        return cab, filas, [("orden_modificado", None)]
    if tipo == "Solo datos (control)":
        pos = rnd.choice(_columnas_de_tipo(perfil, {"entero"}) or _columnas_de_tipo(perfil, {"decimal"}))
        for f in rnd.sample(filas, max(1, len(filas) // 10)):
            if f[pos].strip():
                f[pos] = str(int(float(f[pos].replace(",", "."))) + 1)
        return cab, filas, []
    if tipo == "Nulos (control)":
        candidatas = [i for i, c in enumerate(perfil) if c["tipo"] != "vacia"]
        pos = rnd.choice(candidatas)
        llenas = [f for f in filas if f[pos].strip()]
        for f in rnd.sample(llenas, max(1, len(llenas) // 10)) if len(llenas) > 1 else []:
            f[pos] = ""
        return cab, filas, []
    if tipo == "Formato de fecha":
        iso = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
        candidatas = [
            i for i in _columnas_de_tipo(perfil, {"fecha"}) if any(iso.match(f[i]) for f in filas)
        ]
        pos = rnd.choice(candidatas)
        for f in filas:
            m = iso.match(f[pos])
            if m:
                f[pos] = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
        return cab, filas, [("formato_modificado", cab[pos])]
    raise ValueError(tipo)


TIPOS = [
    "Columna añadida", "Columna eliminada", "Columna renombrada", "Tipo modificado",
    "Orden modificado", "Solo datos (control)", "Nulos (control)",
]


def evaluar_controlada():
    rnd = random.Random(SEMILLA)
    manifiesto = json.loads((DIR_HISTORIAL / "manifiesto.json").read_text(encoding="utf-8"))
    base = rnd.sample(manifiesto, VERSIONES_BASE)
    datos = []
    for m in base:
        cab, filas = leer_csv((DIR_HISTORIAL / m["archivo_local"]).read_bytes())
        datos.append((m["archivo_local"], cab, filas, perfilar_columnas(cab, filas)))
    resultados = {}
    for tipo in TIPOS + ["Formato de fecha"]:
        esperados = detectados = falsos = exactos = 0
        for _ in range(ENSAYOS):
            if tipo == "Formato de fecha":
                iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
                elegibles = [
                    d for d in datos
                    if any(c["tipo"] == "fecha" and d[2] and iso.match(d[2][0][i]) for i, c in enumerate(d[3]))
                ]
            else:
                elegibles = datos
            _, cab, filas, perfil = rnd.choice(elegibles)
            cab2, filas2, esperado = inyectar(tipo, cab, filas, perfil, rnd)
            obtenido = [(c["tipo"], c["columna"]) for c in detectar_cambios(perfil, perfilar_columnas(cab2, filas2))]
            esp, obt = Counter(esperado), Counter(obtenido)
            if tipo == "Formato de fecha":
                # El detector no tiene un tipo "formato": cuenta como detectado si informa algún cambio en esa columna
                col = esperado[0][1]
                acierto = sum(1 for c in obtenido if c[1] == col)
                detectados += min(acierto, 1)
                falsos += sum(1 for c in obtenido if c[1] != col)
                exactos += acierto >= 1 and len(obtenido) == 1
            else:
                detectados += sum((esp & obt).values())
                falsos += sum((obt - esp).values())
                exactos += esp == obt
            esperados += len(esperado)
        resultados[tipo] = {
            "ensayos": ENSAYOS, "cambios_esperados": esperados, "detectados": detectados,
            "falsos_positivos": falsos, "acierto_exacto_pct": round(100 * exactos / ENSAYOS, 1),
        }
        print(f"  {tipo:22s} esperados {esperados:4d}  detectados {detectados:4d}  "
              f"FP {falsos:3d}  acierto {100 * exactos / ENSAYOS:5.1f} %")
    estructurales = [resultados[t] for t in TIPOS]
    aciertos = sum(r["acierto_exacto_pct"] * r["ensayos"] / 100 for r in estructurales)
    total = sum(r["ensayos"] for r in estructurales)
    con_formato = aciertos + resultados["Formato de fecha"]["acierto_exacto_pct"] * ENSAYOS / 100
    return {
        "versiones_base": [d[0] for d in datos],
        "por_tipo": resultados,
        "tasa_acierto_pct": round(100 * aciertos / total, 1),
        "ensayos_acertados": int(round(aciertos)),
        "ensayos": total,
        "tasa_si_se_cuenta_formato_pct": round(100 * con_formato / (total + ENSAYOS), 1),
    }


def main():
    print("1) Historial real")
    real = evaluar_historial()
    print(f"  Referencia: {real['cambios_referencia']} cambios en {real['transiciones_con_cambios']} transiciones; "
          f"detectados {real['detectados_correctamente']}, no detectados {real['no_detectados']}, "
          f"falsos positivos {real['falsos_positivos']}")
    for t in real["cambios_de_tipo_detectados"]:
        print(f"  Cambio de tipo: {t['fecha']} {t['archivo']} {t['columna']} ({t['detalle']})")
    print("2) Prueba controlada")
    ctrl = evaluar_controlada()
    print(f"  Tasa de acierto: {ctrl['tasa_acierto_pct']} % ({ctrl['ensayos_acertados']}/{ctrl['ensayos']}); "
          f"contando el formato de fecha: {ctrl['tasa_si_se_cuenta_formato_pct']} %")
    DIR_RESULTADOS.mkdir(exist_ok=True)
    (DIR_RESULTADOS / "deteccion.json").write_text(
        json.dumps({"historial_real": real, "prueba_controlada": ctrl}, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
