"""Descarga el modelo all-MiniLM-L6-v2 exportado a ONNX y verifica su hash SHA-256.

Uso:  python scripts/descargar_modelo.py
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogo.config import DIR_MODELO  # noqa: E402
from catalogo.embeddings import ARCHIVOS_MODELO, sha256_archivo  # noqa: E402


def main():
    DIR_MODELO.mkdir(parents=True, exist_ok=True)
    for nombre, (url, esperado) in ARCHIVOS_MODELO.items():
        destino = DIR_MODELO / nombre
        if destino.exists() and sha256_archivo(destino) == esperado:
            print(f"{nombre}: ya descargado y verificado.")
            continue
        print(f"Descargando {nombre}...")
        urllib.request.urlretrieve(url, destino)
        if sha256_archivo(destino) != esperado:
            destino.unlink()
            sys.exit(f"El hash SHA-256 de {nombre} no coincide; se eliminó el archivo.")
        print(f"{nombre}: verificado (SHA-256 {esperado[:16]}…).")


if __name__ == "__main__":
    main()
