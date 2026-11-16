"""Modelo all-MiniLM-L6-v2 ejecutado con ONNX Runtime (mean pooling y normalización L2)."""
import hashlib

import numpy as np

from .config import DIR_MODELO

# Exportación a ONNX del modelo original (sentence-transformers/all-MiniLM-L6-v2),
# fijada a una revisión concreta y verificada por su hash SHA-256.
_REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
ARCHIVOS_MODELO = {
    "model.onnx": (
        f"https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/{_REVISION}/onnx/model.onnx",
        "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e",
    ),
    "tokenizer.json": (
        f"https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/{_REVISION}/tokenizer.json",
        "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    ),
}

LONGITUD_MAXIMA = 256  # max_seq_length de all-MiniLM-L6-v2 en sentence-transformers


def sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def verificar_modelo():
    """Comprueba que los archivos del modelo existen y que su hash es el esperado."""
    for nombre, (_, esperado) in ARCHIVOS_MODELO.items():
        ruta = DIR_MODELO / nombre
        if not ruta.exists():
            raise FileNotFoundError(
                f"Falta {ruta}. Ejecute: python scripts/descargar_modelo.py"
            )
        if sha256_archivo(ruta) != esperado:
            raise ValueError(f"El hash SHA-256 de {ruta} no coincide con el esperado")


class Embedder:
    def __init__(self, verificar=True):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if verificar:
            verificar_modelo()
        self.tokenizer = Tokenizer.from_file(str(DIR_MODELO / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=LONGITUD_MAXIMA)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        opciones = ort.SessionOptions()
        opciones.log_severity_level = 3
        self.sesion = ort.InferenceSession(
            str(DIR_MODELO / "model.onnx"), opciones, providers=["CPUExecutionProvider"]
        )

    def codificar(self, textos, lote=32):
        """Devuelve una matriz (n, 384) de embeddings normalizados."""
        salida = []
        for i in range(0, len(textos), lote):
            codif = self.tokenizer.encode_batch(textos[i : i + lote])
            ids = np.array([c.ids for c in codif], dtype=np.int64)
            mascara = np.array([c.attention_mask for c in codif], dtype=np.int64)
            tipos = np.array([c.type_ids for c in codif], dtype=np.int64)
            (ocultos,) = self.sesion.run(
                ["last_hidden_state"],
                {"input_ids": ids, "attention_mask": mascara, "token_type_ids": tipos},
            )
            m = mascara[:, :, None].astype(np.float32)
            medias = (ocultos * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            medias /= np.clip(np.linalg.norm(medias, axis=1, keepdims=True), 1e-12, None)
            salida.append(medias.astype(np.float32))
        return np.vstack(salida) if salida else np.zeros((0, 384), dtype=np.float32)


_instancia = None


def obtener_embedder():
    global _instancia
    if _instancia is None:
        _instancia = Embedder()
    return _instancia
