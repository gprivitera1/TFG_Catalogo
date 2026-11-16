"""Evaluación de la búsqueda (secciones VI-C y VII-E: Tablas VI y VII, Fig. 5).

Ejecuta las 100 consultas de eval/consultas.json con la búsqueda literal, la semántica y la híbrida,
y calcula Precision@10 (y su versión normalizada), Recall@10, MRR, nDCG@10 y Éxito@10, por método
y por tipo de consulta (L: vocabulario de los metadatos; P: paráfrasis). Compara los métodos con la
prueba de Wilcoxon sobre el nDCG@10 de cada consulta.

Uso:  python scripts/exp_busqueda.py
"""
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.busqueda import buscar_hibrida, buscar_literal, buscar_semantica  # noqa: E402
from catalogo.config import DIR_EVAL, DIR_RESULTADOS  # noqa: E402
from catalogo.db import get_connection  # noqa: E402

K = 10
METODOS = {"Literal (ILIKE)": buscar_literal, "Semántica": buscar_semantica, "Híbrida (RRF)": buscar_hibrida}


def relevantes_de(consulta, anotaciones):
    if consulta.get("relevantes"):
        return set(consulta["relevantes"])
    if not consulta.get("etiquetas"):
        return None
    etiquetas = set(consulta["etiquetas"])
    return {
        archivo
        for archivo, a in anotaciones.items()
        if etiquetas <= set(a.get("etiquetas") or [])
        and (not consulta.get("nivel") or a.get("nivel") == consulta["nivel"])
    }


def metricas(ranking, relevantes):
    top = ranking[:K]
    aciertos = [1 if d in relevantes else 0 for d in top]
    r = len(relevantes)
    p10 = sum(aciertos) / K
    maximo = min(r, K) / K
    dcg = sum(a / math.log2(i + 2) for i, a in enumerate(aciertos))
    idcg = sum(1 / math.log2(i + 2) for i in range(min(r, K)))
    primero = next((i for i, a in enumerate(aciertos) if a), None)
    return {
        "p10": p10,
        "p10_norm": p10 / maximo if maximo else 0.0,
        "r10": sum(aciertos) / r if r else 0.0,
        "mrr": 1 / (primero + 1) if primero is not None else 0.0,
        "ndcg10": dcg / idcg if idcg else 0.0,
        "exito10": 1.0 if primero is not None else 0.0,
        "p10_max": maximo,
    }


def media(lista, clave):
    return round(statistics.mean(m[clave] for m in lista), 3) if lista else None


def main():
    datos = json.loads((DIR_EVAL / "consultas.json").read_text(encoding="utf-8"))
    anotaciones = datos["datasets"]
    consultas = datos["consultas"]
    sin_anotar = [c["id"] for c in consultas if relevantes_de(c, anotaciones) is None]
    if sin_anotar:
        sys.exit(
            f"Faltan los juicios de relevancia de {len(sin_anotar)} consultas en eval/consultas.json "
            f"(por ejemplo, ids {sin_anotar[:5]}). Complete las etiquetas de los datasets y de las consultas."
        )

    with get_connection() as conn:
        id_a_archivo = dict(conn.execute("SELECT id, archivo FROM datasets").fetchall())

    diferencias = []
    por_metodo = {m: [] for m in METODOS}
    tiempos = {m: [] for m in METODOS}
    for c in consultas:
        rel = relevantes_de(c, anotaciones)
        if c.get("relevantes_segun_tesis") is not None and len(rel) != c["relevantes_segun_tesis"]:
            diferencias.append((c["id"], len(rel), c["relevantes_segun_tesis"]))
        for nombre, buscar in METODOS.items():
            t0 = time.perf_counter()
            ids = buscar(c["texto"], k=K)
            tiempos[nombre].append((time.perf_counter() - t0) * 1000)
            ranking = [id_a_archivo[i] for i in ids]
            m = metricas(ranking, rel)
            m.update({"id": c["id"], "tipo": c["tipo"], "top": ranking})
            por_metodo[nombre].append(m)

    tabla = {}
    for nombre, lista in por_metodo.items():
        tabla[nombre] = {
            k: media(lista, k) for k in ("p10", "p10_norm", "r10", "mrr", "ndcg10", "exito10")
        }
        tabla[nombre]["ndcg10_L"] = media([m for m in lista if m["tipo"] == "L"], "ndcg10")
        tabla[nombre]["ndcg10_P"] = media([m for m in lista if m["tipo"] == "P"], "ndcg10")
        tabla[nombre]["p95_ms"] = round(sorted(tiempos[nombre])[94], 1)
    tabla["Máximo alcanzable"] = {"p10": media(por_metodo["Semántica"], "p10_max")}

    pruebas = {}
    try:
        from scipy.stats import wilcoxon

        def p(a, b, tipo=None):
            xa = [m["ndcg10"] for m in por_metodo[a] if tipo in (None, m["tipo"])]
            xb = [m["ndcg10"] for m in por_metodo[b] if tipo in (None, m["tipo"])]
            return round(float(wilcoxon(xa, xb).pvalue), 3)

        pruebas = {
            "semantica_vs_literal": p("Semántica", "Literal (ILIKE)"),
            "semantica_vs_literal_L": p("Semántica", "Literal (ILIKE)", "L"),
            "semantica_vs_literal_P": p("Semántica", "Literal (ILIKE)", "P"),
            "hibrida_vs_literal": p("Híbrida (RRF)", "Literal (ILIKE)"),
            "hibrida_vs_semantica": p("Híbrida (RRF)", "Semántica"),
        }
    except ImportError:
        print("scipy no está instalado: se omiten las pruebas de Wilcoxon.")

    paraf = [c for c in consultas if c["tipo"] == "P"]
    lit_vacia = sum(
        1 for m in por_metodo["Literal (ILIKE)"] if m["tipo"] == "P" and not m["top"]
    )
    exito_p = {n: media([m for m in l if m["tipo"] == "P"], "exito10") for n, l in por_metodo.items()}

    salida = {
        "metricas": tabla, "wilcoxon_p": pruebas,
        "parafrasis": {"total": len(paraf), "literal_sin_resultados": lit_vacia, "exito10": exito_p},
        "diferencias_con_tabla_X": diferencias, "por_consulta": por_metodo,
    }
    DIR_RESULTADOS.mkdir(exist_ok=True)
    (DIR_RESULTADOS / "busqueda.json").write_text(json.dumps(salida, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{'Método':18s} {'P@10':>6s} {'norm':>6s} {'R@10':>6s} {'MRR':>6s} {'nDCG':>6s} {'Éxito':>6s} {'L':>6s} {'P':>6s}")
    for n, t in tabla.items():
        if n == "Máximo alcanzable":
            print(f"{n:18s} {t['p10']:6.3f}")
            continue
        print(f"{n:18s} {t['p10']:6.3f} {t['p10_norm']:6.3f} {t['r10']:6.3f} {t['mrr']:6.3f} {t['ndcg10']:6.3f} "
              f"{t['exito10']:6.2f} {t['ndcg10_L']:6.3f} {t['ndcg10_P']:6.3f}")
    print("Wilcoxon (p):", pruebas)
    print(f"Paráfrasis sin resultados en la literal: {lit_vacia} de {len(paraf)}; Éxito@10 en paráfrasis: {exito_p}")
    if diferencias:
        print(f"ATENCIÓN: {len(diferencias)} consultas tienen una cantidad de relevantes distinta de la Tabla X "
              f"(id, anotados, tesis): {diferencias[:10]}")


if __name__ == "__main__":
    main()
