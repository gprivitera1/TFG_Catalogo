"""Rendimiento de la interfaz (secciones VI-D y VII-F: Tabla VIII).

Con un navegador automatizado (Playwright) registra el tiempo desde cada acción del usuario hasta que
la página termina de actualizarse: 10 búsquedas, 4 cambios de dataset y 40 movimientos del slider.

Requisitos:  pip install playwright && python -m playwright install chromium
Uso:         1) streamlit run app.py      2) python scripts/exp_interfaz.py [--url http://localhost:8501]
"""
import argparse
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_RESULTADOS  # noqa: E402

BUSQUEDAS = [
    "dónde repostar combustible durante el confinamiento", "casos por provincia", "vacunas por comunidad",
    "propiedades registradas por los obispados", "camas de UCI", "expedientes de regulación de empleo",
    "fallecidos por fecha de defunción", "terceras dosis para mayores de 70 años",
    "positivos asintomáticos por comunidad", "caudal de la rambla del Poyo",
]


def esperar_fin(page, timeout=30):
    """Espera a que Streamlit deje de ejecutar el script (desaparece el indicador 'Running')."""
    time.sleep(0.05)
    inicio = time.perf_counter()
    while time.perf_counter() - inicio < timeout:
        if page.locator('[data-testid="stStatusWidget"]').count() == 0:
            return
        time.sleep(0.01)
    raise TimeoutError("La página no terminó de actualizarse")


def resumen(v):
    v = sorted(v)
    return {"n": len(v), "media": statistics.mean(v), "mediana": statistics.median(v),
            "p95": v[int(round(0.95 * (len(v) - 1)))], "maximo": v[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8501")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    rnd = random.Random(2026)
    t = {"Búsqueda": [], "Cambio de dataset": [], "Movimiento del slider": []}
    detalle_slider = []
    with sync_playwright() as p:
        nav = p.chromium.launch()
        page = nav.new_page(viewport={"width": 1400, "height": 900})
        page.goto(args.url)
        page.wait_for_selector('[data-testid="stSelectbox"]', timeout=60000)
        esperar_fin(page)

        entrada = page.get_by_label("Buscar dataset")
        entrada.fill("calentamiento")
        entrada.press("Enter")
        esperar_fin(page)
        selector = page.locator('[data-testid="stSelectbox"]')
        for i in range(4):
            selector.click()
            page.locator('[role="option"]').nth(i).click()
            esperar_fin(page)
        for q in BUSQUEDAS:
            entrada.fill(q)
            t0 = time.perf_counter()
            entrada.press("Enter")
            esperar_fin(page)
            t["Búsqueda"].append((time.perf_counter() - t0) * 1000)

        selector = page.locator('[data-testid="stSelectbox"]')
        for i in [1, 2, 3, 0]:
            selector.click()
            opcion = page.locator('[role="option"]').nth(i)
            t0 = time.perf_counter()
            opcion.click()
            esperar_fin(page)
            t["Cambio de dataset"].append((time.perf_counter() - t0) * 1000)

        for i in range(40):
            if i % 10 == 0:  # recorre las cuatro series
                selector.click()
                page.locator('[role="option"]').nth(i // 10).click()
                esperar_fin(page)
            manija = page.locator('[data-testid="stSlider"] input').first
            manija.focus()
            tecla = rnd.choice(["ArrowLeft", "ArrowRight", "PageDown", "PageUp", "Home", "End"])
            t0 = time.perf_counter()
            manija.press(tecla)
            esperar_fin(page)
            t["Movimiento del slider"].append((time.perf_counter() - t0) * 1000)
            detalle_slider.append({"dataset_opcion": i // 10,
                                   "ms": t["Movimiento del slider"][-1]})
        nav.close()

    resultados = {k: resumen(v) for k, v in t.items()}
    resultados["detalle_slider"] = detalle_slider
    for k, r in resultados.items():
        if k == "detalle_slider":
            continue
        print(f"{k:22s} n={r['n']:3d} media {r['media']:6.0f} ms  mediana {r['mediana']:6.0f}  "
              f"P95 {r['p95']:6.0f}  máx {r['maximo']:6.0f}")
    DIR_RESULTADOS.mkdir(exist_ok=True)
    (DIR_RESULTADOS / "interfaz.json").write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
