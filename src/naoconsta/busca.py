"""Recuperação: densa (pgvector), lexical (BM25) e as duas baselines triviais.

Nenhum número de sistema é publicável sem um baseline que o ameace — disciplina herdada do
RodoQuery, onde o valor da interface só ficou claro contra o SQL cru. Aqui há **três**:

- **BM25**, o adversário sério. Contrato é texto jurídico com termos raros e literais
  ("escrow", "most favored nation"); busca lexical costuma ir muito bem nisso, e se a densa não
  a superar, o banco vetorial não se paga.
- **primeiro chunk** (`primeiros`), o espantalho posicional. `Document Name` e `Parties` estão em
  100% dos contratos e no começo deles; a dispersão mediana dos spans é 0,04. Um sistema que
  devolve sempre os k primeiros chunks já acerta uma fatia — e essa fatia não é mérito de
  recuperação nenhuma.
- **aleatório**, o piso. Diz quanto do recall é sorte, dado que o contrato mediano tem ~33 chunks
  e k é pequeno.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter

import numpy as np

MODELO_EMBED = os.environ.get("NAOCONSTA_MODELO_EMBED", "nomic-embed-text")
OLLAMA = os.environ.get("NAOCONSTA_OLLAMA_URL", "http://localhost:11434")
DSN = os.environ.get(
    "NAOCONSTA_PG_DSN",
    "host=localhost port=5433 user=postgres password=naoconsta dbname=naoconsta",
)
DIMS = 768  # nomic-embed-text


# --------------------------------------------------------------------------- embeddings
def embutir(textos: list[str], modelo: str = MODELO_EMBED) -> np.ndarray:
    """Chama o Ollama em lote. `urllib` da stdlib de propósito: uma dependência a menos e o
    contrato é HTTP puro, então trocar de provedor não exige trocar de biblioteca."""
    corpo = json.dumps({"model": modelo, "input": textos}).encode()
    req = urllib.request.Request(f"{OLLAMA}/api/embed", data=corpo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        dados = json.loads(r.read())
    v = np.asarray(dados["embeddings"], dtype=np.float32)
    # Normaliza aqui, uma vez: com vetores unitários a distância de cosseno do pgvector e o
    # produto interno concordam, e o BM25 fica sendo a única escala diferente no experimento.
    return v / np.clip(np.linalg.norm(v, axis=1, keepdims=True), 1e-12, None)


# --------------------------------------------------------------------------- BM25
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenizar(t: str) -> list[str]:
    return _TOKEN.findall(t.lower())


class BM25:
    """BM25 escrito à mão (k1=1.5, b=0.75) para NÃO herdar as escolhas de uma biblioteca.

    É por contrato: o índice é pequeno (~33 chunks) e a comparação com a densa tem de ser no
    mesmo escopo, senão não é comparação.
    """

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b, self.docs = k1, b, docs
        self.n = len(docs)
        self.lens = np.array([len(d) for d in docs], dtype=np.float32)
        self.avg = float(self.lens.mean()) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def pontuar(self, consulta: list[str]) -> np.ndarray:
        s = np.zeros(self.n, dtype=np.float32)
        for termo in consulta:
            idf = self.idf.get(termo)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(termo, 0)
                if f:
                    den = f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
                    s[i] += idf * f * (self.k1 + 1) / den
        return s


# --------------------------------------------------------------------------- pgvector
ESQUEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;
DROP TABLE IF EXISTS pedaco;
CREATE TABLE pedaco (
    id        bigserial PRIMARY KEY,
    contrato  text        NOT NULL,
    ordem     int         NOT NULL,
    inicio    int         NOT NULL,
    fim       int         NOT NULL,
    texto     text        NOT NULL,
    vetor     vector({DIMS}) NOT NULL
);
-- Índice B-tree no filtro ANTES do índice vetorial: a consulta real é
-- "os k mais próximos DENTRO deste contrato", e sem ele o filtro varre a tabela toda.
CREATE INDEX pedaco_contrato ON pedaco (contrato);
"""

# HNSW só depois da carga: construir com a tabela cheia é muito mais rápido que manter o índice
# atualizado a cada insert. `vector_cosine_ops` porque os vetores são unitários.
INDICE_HNSW = """
CREATE INDEX IF NOT EXISTS pedaco_vetor
    ON pedaco USING hnsw (vetor vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""
