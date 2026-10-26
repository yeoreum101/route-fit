"""② 문장 임베딩 기반 취향 매칭: 장소 설명 벡터와 사용자 취향 벡터의 코사인 유사도."""
import logging
import zlib
from functools import lru_cache
from typing import Protocol

import numpy as np

from . import config
from .models import Place

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """L2 정규화된 (len(texts), dim) 행렬."""


class OpenAIEmbedder:
    """OpenAI 임베딩 API. 모델을 내려받지 않아 서버가 바로 뜨고, Docker 이미지에도 torch 가 필요 없다."""

    BATCH = 512  # 요청 한 번에 보내는 문장 수

    def __init__(self, model_name: str):
        import os

        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 가 비어 있습니다")
        self.name = f"openai:{model_name}"
        self._model = model_name
        self._client = OpenAI(api_key=api_key, timeout=30.0)
        self.encode(["광주"])  # 키·모델이 맞는지 시작할 때 확인한다

    def encode(self, texts: list[str]) -> np.ndarray:
        rows = []
        for i in range(0, len(texts), self.BATCH):
            res = self._client.embeddings.create(model=self._model, input=texts[i : i + self.BATCH])
            rows.extend(d.embedding for d in sorted(res.data, key=lambda d: d.index))
        out = np.asarray(rows, dtype=np.float32)
        return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


class SbertEmbedder:
    """한국어 문장 임베딩 모델 (sentence-transformers)."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.name = f"sbert:{model_name}"
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._model.encode(texts, normalize_embeddings=True))


class HashingEmbedder:
    """문자 n-gram 해싱 벡터. 모델 없이 파이프라인을 돌리기 위한 개발용 대체재로,
    의미가 아닌 글자 겹침만 본다. 실증 전에는 반드시 sbert 로 교체한다."""

    name = "hashing"

    def __init__(self, dim: int = 2048):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in text.lower().split():
                for n in (2, 3):
                    for i in range(max(len(word) - n + 1, 1)):
                        out[row, zlib.crc32(word[i : i + n].encode()) % self.dim] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)


@lru_cache
def get_embedder() -> Embedder:
    if config.EMBEDDER in ("auto", "openai"):
        try:
            return OpenAIEmbedder(config.OPENAI_EMBED_MODEL)
        except Exception as e:
            if config.EMBEDDER == "openai":
                raise
            log.warning("OpenAI 임베딩을 쓸 수 없어 sbert 로 대체: %s", e)
    if config.EMBEDDER in ("auto", "sbert"):
        try:
            return SbertEmbedder(config.SBERT_MODEL)
        except Exception as e:
            if config.EMBEDDER == "sbert":
                raise
            log.warning("sbert 임베딩을 쓸 수 없어 해싱 임베딩으로 대체: %s", e)
    return HashingEmbedder()


class PlaceIndex:
    """장소 벡터를 한 번만 계산해 두고 취향 문장과의 유사도를 돌려준다."""

    def __init__(self, places: list[Place], embedder: Embedder):
        self.embedder = embedder
        self.source = places
        self.ids = [p.id for p in places]
        self.matrix = embedder.encode([p.embed_text for p in places])

    def similarities(self, taste: str) -> dict[str, float]:
        query = self.embedder.encode([taste])[0]
        return dict(zip(self.ids, (self.matrix @ query).tolist()))
