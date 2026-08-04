"""Fase 1b — a alavanca que faltava: trocar o modelo de embedding levanta o portao?

Mede numa AMOSTRA de contratos antes de reindexar tudo. Reindexar os 26.952 chunks com um modelo
4x maior custa ~25 min de GPU; a amostra responde em ~3. Se a diferenca nao aparecer aqui, ela
nao vale a reindexacao — e se aparecer, a reindexacao vira decisao com numero, nao aposta.

O protocolo e o mesmo da Fase 1, com uma diferenca declarada: a similaridade dos dois modelos e
calculada em numpy sobre a MESMA amostra e o MESMO gold, entao a unica variavel e o modelo.
"""
import json
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from naoconsta import busca, corpus

N_CONTRATOS = int(sys.argv[1]) if len(sys.argv) > 1 else 60
MODELOS = {"nomic-embed-text": 768, "bge-m3": 1024}
KS = (1, 5, 10)
SEMENTE = 20260803
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "comparacao_modelos.json"


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n))


def main() -> int:
    pedacos, consultas, _ = corpus.carregar()
    chunks: dict[str, list[corpus.Pedaco]] = defaultdict(list)
    for p in pedacos:
        chunks[p.contrato].append(p)
    for k in chunks:
        chunks[k].sort(key=lambda p: p.ordem)

    rng = random.Random(SEMENTE)
    amostra = set(rng.sample(sorted(chunks), N_CONTRATOS))
    alvo = [c for c in consultas if c.respondivel and c.contrato in amostra]
    distintas = sorted({c.pergunta for c in alvo})
    n_chunks = sum(len(chunks[c]) for c in amostra)
    print(f"amostra: {len(amostra)} contratos, {n_chunks:,} chunks, "
          f"{len(alvo):,} consultas respondiveis, {len(distintas)} perguntas distintas")

    gold = {}
    for i, c in enumerate(alvo):
        gold[i] = {p.ordem for p in chunks[c.contrato]
                   if any(corpus.relevante(p, s) for s in c.spans)}
    validos = [i for i in gold if gold[i]]

    acertos: dict[str, dict[int, set[int]]] = {}
    art: dict = {"n_contratos": len(amostra), "n_chunks": n_chunks,
                 "n_consultas": len(validos), "semente": SEMENTE, "modelos": {}}

    for modelo, dims in MODELOS.items():
        t0 = time.perf_counter()
        # Perguntas ENXUTAS: e a forma consertada na Fase 1, entao a comparacao entre modelos
        # acontece no melhor regime de cada um, nao no defeito.
        VQ = dict(zip(distintas,
                      busca.embutir([corpus.enxugar(q) for q in distintas], modelo=modelo),
                      strict=True))
        M, ordens = {}, {}
        for nome in sorted(amostra):
            ps = chunks[nome]
            M[nome] = busca.embutir([p.texto for p in ps], modelo=modelo)
            ordens[nome] = [p.ordem for p in ps]
        dur = time.perf_counter() - t0

        acertos[modelo] = {k: set() for k in KS}
        for i in validos:
            c = alvo[i]
            sim = M[c.contrato] @ VQ[c.pergunta]
            ordem_topo = [ordens[c.contrato][j] for j in np.argsort(-sim)]
            for k in KS:
                if set(ordem_topo[:k]) & gold[i]:
                    acertos[modelo][k].add(i)

        art["modelos"][modelo] = {
            "dims": dims, "segundos": round(dur, 1),
            "chunks_por_segundo": round(n_chunks / dur, 1),
            **{f"recall@{k}": round(len(acertos[modelo][k]) / len(validos), 4) for k in KS},
        }
        r = art["modelos"][modelo]
        print(f"  {modelo:18s} {dims}d  {dur:6.1f}s ({r['chunks_por_segundo']:5.1f} ch/s)  "
              + "  ".join(f"@{k} {r[f'recall@{k}']:.1%}" for k in KS))

    a, b = MODELOS
    print("\nMcNemar pareado (bge-m3 x nomic), na mesma amostra e mesmo gold:")
    for k in KS:
        g = len(acertos[b][k] - acertos[a][k])
        p_ = len(acertos[a][k] - acertos[b][k])
        art.setdefault("mcnemar", {})[f"@{k}"] = {"bge_ganha": g, "nomic_ganha": p_,
                                                  "p": mcnemar(g, p_)}
        delta = art["modelos"][b][f"recall@{k}"] - art["modelos"][a][f"recall@{k}"]
        print(f"  @{k:<3d} bge {g:4d} x {p_:4d} nomic   delta {delta:+.1%}   "
              f"p={mcnemar(g, p_):.4g}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
