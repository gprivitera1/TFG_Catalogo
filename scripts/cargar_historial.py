"""Carga en PostgreSQL, con versionado incremental, el historial extraído por extraer_historial.py.

Uso:  python scripts/cargar_historial.py [--reiniciar]

--reiniciar  borra la base de datos y la vuelve a crear antes de cargar.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_HISTORIAL, DIR_RESULTADOS, SERIES, titulo_desde_archivo  # noqa: E402
from catalogo.db import get_connection, init_db, reiniciar_db  # noqa: E402
from catalogo.versionado import ingerir, registrar_dataset  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reiniciar", action="store_true")
    args = ap.parse_args()

    manifiesto_ruta = DIR_HISTORIAL / "manifiesto.json"
    if not manifiesto_ruta.exists():
        sys.exit("No se encontró el historial. Ejecute primero: python scripts/extraer_historial.py")
    manifiesto = json.loads(manifiesto_ruta.read_text(encoding="utf-8"))

    if args.reiniciar:
        reiniciar_db()
    else:
        init_db()

    resumen = {}
    with get_connection() as conn:
        for serie, cfg in SERIES.items():
            ya = conn.execute(
                "SELECT count(*) FROM versiones v JOIN datasets d ON d.id = v.dataset_id WHERE d.archivo = %s",
                (cfg["archivo"],),
            ).fetchone()[0]
            if ya:
                print(f"{serie}: ya cargada ({ya} versiones). Use --reiniciar para recargar.")
                continue
            dataset_id = registrar_dataset(
                conn, titulo_desde_archivo(cfg["archivo"]), "Datadista (Ministerio de Sanidad / ISCIII)",
                archivo=cfg["archivo"],
            )
            conn.commit()
            archivos = [m for m in manifiesto if m["serie"] == serie]
            registradas = descartadas = 0
            tiempos = []
            for m in archivos:
                contenido = (DIR_HISTORIAL / m["archivo_local"]).read_bytes()
                t0 = time.perf_counter()
                r = ingerir(
                    conn, dataset_id, contenido, m["fecha"], cfg["claves"],
                    metadatos={"commit": m["commit"], "ruta": m["ruta"], "bytes": len(contenido)},
                )
                conn.commit()
                tiempos.append(time.perf_counter() - t0)
                if r is None:
                    descartadas += 1
                else:
                    registradas += 1
            resumen[serie] = {
                "archivos": len(archivos),
                "versiones": registradas,
                "descartadas_por_hash": descartadas,
                "ingesta_max_s": round(max(tiempos), 3),
                "ingesta_media_s": round(sum(tiempos) / len(tiempos), 3),
            }
            print(f"{serie}: {registradas} versiones ({descartadas} descartadas por hash idéntico); "
                  f"ingesta máx. {max(tiempos):.2f} s")

    if resumen:
        DIR_RESULTADOS.mkdir(exist_ok=True)
        (DIR_RESULTADOS / "carga.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
