"""Volumen versionado, exactitud de la restauración, espacio en disco y revisión de datos ya publicados
(secciones VII-A y VII-B: Tabla II y Fig. 3).

Uso:  python scripts/exp_volumen.py
"""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_HISTORIAL, DIR_RESULTADOS, SERIES  # noqa: E402
from catalogo.db import get_connection  # noqa: E402
from catalogo.versionado import leer_csv, listar_versiones, restaurar_version  # noqa: E402

FECHA_REVISION = "2020-11-02"  # día analizado en la Fig. 3


def id_serie(conn, serie):
    return conn.execute("SELECT id FROM datasets WHERE archivo = %s", (SERIES[serie]["archivo"],)).fetchone()[0]


def main():
    manifiesto = json.loads((DIR_HISTORIAL / "manifiesto.json").read_text(encoding="utf-8"))
    por_commit = {(m["serie"], m["commit"]): m for m in manifiesto}
    resultado = {"series": {}, "exactitud": {}}
    bytes_csv = 0

    with get_connection() as conn:
        for serie in SERIES:
            did = id_serie(conn, serie)
            versiones = listar_versiones(did, conn)
            total = sum(v["metadatos"]["filas"] for v in versiones)
            guardadas = conn.execute("SELECT count(*) FROM registros WHERE dataset_id = %s", (did,)).fetchone()[0]
            resultado["series"][serie] = {
                "versiones": len(versiones),
                "filas_ultima_version": versiones[-1]["metadatos"]["filas"],
                "filas_todas_las_versiones": total,
                "filas_guardadas": guardadas,
                "ahorro_pct": round(100 * (1 - guardadas / total), 1),
            }

            # Exactitud: cada versión restaurada debe coincidir con su CSV original
            exactas = 0
            for v in versiones:
                m = por_commit[(serie, v["metadatos"]["commit"])]
                contenido = (DIR_HISTORIAL / m["archivo_local"]).read_bytes()
                bytes_csv += len(contenido)
                cab, filas = leer_csv(contenido)
                esperado = Counter(tuple(sorted(zip(cab, f))) for f in filas)
                restaurado = Counter(
                    tuple(sorted(d.items())) for d in restaurar_version(did, fecha=v["valid_from"], conn=conn)
                )
                exactas += esperado == restaurado
            resultado["exactitud"][serie] = {"versiones": len(versiones), "exactas": exactas}
            print(f"{serie}: {len(versiones)} versiones, {exactas} restauradas de forma exacta")

        tot = {
            "versiones": sum(s["versiones"] for s in resultado["series"].values()),
            "filas_todas_las_versiones": sum(s["filas_todas_las_versiones"] for s in resultado["series"].values()),
            "filas_guardadas": sum(s["filas_guardadas"] for s in resultado["series"].values()),
        }
        tot["ahorro_pct"] = round(100 * (1 - tot["filas_guardadas"] / tot["filas_todas_las_versiones"]), 1)
        resultado["total"] = tot

        # Se compacta la tabla antes de medir: las filas cerradas con UPDATE dejan versiones muertas
        # que inflan el tamaño hasta que se ejecuta VACUUM, y la medición dejaría de ser reproducible.
        conn.commit()
        conn.autocommit = True
        conn.execute("VACUUM FULL registros")
        conn.autocommit = False
        tabla_bytes, media_fila = conn.execute(
            "SELECT pg_table_size('registros'), avg(length(datos::text)) FROM registros"
        ).fetchone()
        resultado["disco"] = {
            "registros_sin_indices_MB": round(tabla_bytes / 1e6),
            "csv_todas_las_versiones_MB": round(bytes_csv / 1e6),
            "bytes_medios_por_fila_json": round(float(media_fila)),
            "bytes_medios_por_fila_csv": round(bytes_csv / tot["filas_todas_las_versiones"]),
        }

        # Revisión de datos ya publicados (serie por comunidad autónoma)
        did = id_serie(conn, "ccaa_nueva")
        versiones = listar_versiones(did, conn)
        prev_filas, pct_mod, n_mod = None, [], []
        for v in versiones:
            m = v["metadatos"]
            if prev_filas:
                pct_mod.append(100 * m["filas_modificadas"] / prev_filas)
                n_mod.append(m["filas_modificadas"])
            prev_filas = m["filas"]
        serie_dia = []
        for v in versiones:
            fila = conn.execute(
                "SELECT count(*), sum((datos->>'num_casos')::int) FROM registros WHERE dataset_id = %s "
                "AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s) AND datos->>'fecha' = %s",
                (did, v["valid_from"], v["valid_from"], FECHA_REVISION),
            ).fetchone()
            if fila[0]:
                serie_dia.append({"version": v["valid_from"].isoformat(), "casos": fila[1]})
        cambios_valor = sum(1 for a, b in zip(serie_dia, serie_dia[1:]) if a["casos"] != b["casos"])
        maximo = max(serie_dia, key=lambda x: x["casos"])
        resultado["revisiones"] = {
            "pct_medio_filas_modificadas_por_version": round(statistics.mean(pct_mod), 1),
            "mediana_filas_modificadas": statistics.median(n_mod),
            "fecha": FECHA_REVISION,
            "versiones_con_la_fecha": len(serie_dia),
            "primera_cifra": serie_dia[0]["casos"],
            "maximo": maximo,
            "ultima_cifra": serie_dia[-1]["casos"],
            "actualizaciones_que_cambiaron_el_valor": cambios_valor,
            "serie": serie_dia,
        }

    DIR_RESULTADOS.mkdir(exist_ok=True)
    (DIR_RESULTADOS / "volumen.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    r = resultado["revisiones"]
    print(json.dumps({k: resultado[k] for k in ("series", "total", "disco")}, indent=2, ensure_ascii=False))
    print(f"Revisiones del {FECHA_REVISION}: {r['versiones_con_la_fecha']} versiones; primera {r['primera_cifra']}, "
          f"máximo {r['maximo']}, última {r['ultima_cifra']}; cambió en {r['actualizaciones_que_cambiaron_el_valor']} "
          f"actualizaciones. % medio de filas modificadas: {r['pct_medio_filas_modificadas_por_version']}")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from datetime import datetime

        x = [datetime.fromisoformat(s["version"]) for s in r["serie"]]
        y = [s["casos"] for s in r["serie"]]
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.step(x, y, where="post", color="#2a6f97")
        ax.set_ylabel(f"Casos del {FECHA_REVISION}")
        ax.set_xlabel("Fecha de la versión")
        fig.tight_layout()
        fig.savefig(DIR_RESULTADOS / "fig3_revisiones.png", dpi=200)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
