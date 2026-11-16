"""Tiempo de restauración (secciones VI-B y VII-D: Tabla V y Fig. 4).

Mide el tiempo para reconstruir 100 fechas elegidas al azar en cada una de las cuatro series reales
y en dos datasets sintéticos de 10.000 y 100.000 filas (60 versiones mensuales, 2 % de filas revisadas
en cada versión y un cambio estructural en la versión 30). Se comparan la implementación inicial
y la optimizada, y se mide el tiempo de ejecución en el servidor (EXPLAIN ANALYZE).

Uso:  python scripts/exp_restauracion.py
"""
import csv
import gc
import io
import json
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_RESULTADOS, SERIES  # noqa: E402
from catalogo.db import get_connection  # noqa: E402
from catalogo.versionado import SQL_RESTAURAR, ingerir, registrar_dataset, restaurar_version  # noqa: E402

SEMILLA = 2026
FECHAS = 100
REGIONES = ["Norte", "Sur", "Este", "Oeste", "Centro"]


def generar_sintetico(conn, n_filas):
    """Crea (si no existe) un dataset sintético con 60 versiones mensuales."""
    archivo = f"sintetico/{n_filas}"
    did = registrar_dataset(conn, f"Sintético {n_filas:,}".replace(",", "."), "Sintético", archivo=archivo)
    if conn.execute("SELECT count(*) FROM versiones WHERE dataset_id = %s", (did,)).fetchone()[0]:
        return did
    rnd = random.Random(n_filas)
    filas = [
        [str(i), f"2018-01-{1 + i % 28:02d}", REGIONES[i % 5], str(rnd.randint(0, 10_000)),
         f"{rnd.random() * 1000:.2f}", str(rnd.randint(0, 100))]
        for i in range(n_filas)
    ]
    cab = ["id", "fecha", "region", "valor_a", "valor_b", "valor_c"]
    for v in range(1, 61):
        if v > 1:
            for f in rnd.sample(filas, n_filas * 2 // 100):  # 2 % de filas revisadas
                f[3] = str(rnd.randint(0, 10_000))
        if v == 30:  # cambio estructural: se añade una columna
            cab = cab + ["valor_d"]
            for f in filas:
                f.append(str(rnd.randint(0, 50)))
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cab)
        w.writerows(filas)
        fecha = datetime(2018 + (v - 1) // 12, 1 + (v - 1) % 12, 1)
        ingerir(conn, did, buf.getvalue().encode(), fecha, [["id"]])
        conn.commit()
    print(f"  Dataset sintético de {n_filas} filas creado (60 versiones).")
    return did


def resumen(valores):
    valores = sorted(valores)
    return {
        "media": statistics.mean(valores),
        "mediana": statistics.median(valores),
        "p95": valores[int(round(0.95 * (len(valores) - 1)))],
    }


def medir(conn, did, rnd):
    desde, hasta = conn.execute(
        "SELECT min(valid_from), max(valid_from) FROM versiones WHERE dataset_id = %s", (did,)
    ).fetchone()
    fechas = [desde + (hasta - desde) * rnd.random() for _ in range(FECHAS)]
    for f in fechas[:3]:  # calentamiento
        restaurar_version(did, fecha=f, conn=conn)
    t_ini, t_opt, t_srv, n = [], [], [], []
    for f in fechas:
        # Se libera la memoria de la medición anterior para que no afecte a la siguiente
        gc.collect()
        t0 = time.perf_counter()
        filas = restaurar_version(did, fecha=f, optimizada=False, conn=conn)
        t_ini.append((time.perf_counter() - t0) * 1000)
        del filas
        gc.collect()
        t0 = time.perf_counter()
        filas = restaurar_version(did, fecha=f, optimizada=True, conn=conn)
        t_opt.append((time.perf_counter() - t0) * 1000)
        n.append(len(filas))
        del filas
        plan = conn.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + SQL_RESTAURAR.format(cast=""), (did, f, f)
        ).fetchone()[0]
        t_srv.append(plan[0]["Execution Time"])
    return {
        "filas_media": statistics.mean(n),
        "inicial": resumen(t_ini),
        "optimizada": resumen(t_opt),
        "servidor": resumen(t_srv),
    }


def main():
    rnd = random.Random(SEMILLA)
    resultados = {}
    with get_connection() as conn:
        datasets = []
        for serie, cfg in SERIES.items():
            did = conn.execute("SELECT id FROM datasets WHERE archivo = %s", (cfg["archivo"],)).fetchone()[0]
            datasets.append((serie, did))
        datasets.append(("sintetico_10000", generar_sintetico(conn, 10_000)))
        datasets.append(("sintetico_100000", generar_sintetico(conn, 100_000)))
        conn.execute("ANALYZE registros")
        conn.commit()
        for nombre, did in datasets:
            r = medir(conn, did, rnd)
            resultados[nombre] = r
            print(f"  {nombre:18s} filas {r['filas_media']:9.0f}  inicial {r['inicial']['media']:7.1f} ms  "
                  f"optimizada {r['optimizada']['media']:7.1f} ms (P95 {r['optimizada']['p95']:6.1f})  "
                  f"servidor {r['servidor']['media']:6.1f} ms")
    DIR_RESULTADOS.mkdir(exist_ok=True)
    (DIR_RESULTADOS / "restauracion.json").write_text(json.dumps(resultados, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
