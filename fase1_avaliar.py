"""Fase 1 — recall@k contra o offset humano. Sem juiz-LLM em nenhuma parte.

Seis sistemas, porque um número de sistema sem baseline que o ameace não é resultado:

  denso_bruto    pgvector com a pergunta do CUAD como está — a configuração pré-registrada
  denso_enxuto   idem, sem o preâmbulo templado (ver `corpus.enxugar`)
  bm25           BM25 à mão (k1=1,5 b=0,75), mesmo escopo por contrato
  hibrido_rrf    fusão RRF (k=60) de `denso_enxuto` + `bm25`
  primeiros      os k primeiros chunks — espantalho posicional
  aleatorio      k sorteados — o piso da sorte

**Por que a similaridade é calculada em numpy e não por `ORDER BY <=>` no Postgres.** O
`EXPLAIN ANALYZE` mostrou que, com `WHERE contrato = ?` (53 de 26.952 linhas), o planner ignora
o índice HNSW e faz `Sort → top-N heapsort`, isto é, **busca exata**. Como o banco já estava
fazendo cálculo exato, computar o mesmo em numpy dá resultado idêntico e permite rodar os seis
sistemas sobre os MESMOS vetores, sem 40 mil idas ao banco. O que se perde é a ilusão de estar
exercitando ANN — e essa ilusão é justamente o que a Fase 1 documenta como falsa.
"""
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from naoconsta import busca, corpus

KS = (1, 3, 5, 10)
SISTEMAS = ("denso_bruto", "denso_enxuto", "bm25", "hibrido_rrf", "primeiros", "aleatorio")
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "recall.json"
SEMENTE = 20260803
RRF_K = 60


def wilson(acertos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p, d = acertos / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


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

    alvo = [c for c in consultas if c.respondivel]
    print(f"consultas respondiveis: {len(alvo):,}   contratos: {len(chunks)}")

    # 41 textos distintos: embutir 6.702 vezes o mesmo texto seria pagar 163x pelo mesmo vetor.
    distintas = sorted({c.pergunta for c in alvo})
    V_bruto = dict(zip(distintas, busca.embutir(distintas), strict=True))
    V_enxuto = dict(zip(distintas,
                        busca.embutir([corpus.enxugar(q) for q in distintas]), strict=True))
    print(f"textos de pergunta distintos: {len(distintas)} (embutidos nas 2 formas)")

    with psycopg.connect(busca.DSN) as con:
        register_vector(con)
        linhas = con.execute(
            "SELECT contrato, ordem, vetor FROM pedaco ORDER BY contrato, ordem").fetchall()
    M: dict[str, np.ndarray] = {}
    ordens: dict[str, list[int]] = defaultdict(list)
    tmp: dict[str, list] = defaultdict(list)
    for contrato, ordem, v in linhas:
        ordens[contrato].append(ordem)
        tmp[contrato].append(np.asarray(v.to_list(), dtype=np.float32))
    for k, v in tmp.items():
        M[k] = np.vstack(v)
    print(f"vetores lidos do pgvector: {len(linhas):,}")

    bm25 = {n: busca.BM25([busca.tokenizar(p.texto) for p in ps]) for n, ps in chunks.items()}
    rng = random.Random(SEMENTE)
    kmax = max(KS)

    gold: list[set[int]] = []
    topo: dict[str, list[list[int]]] = {s: [] for s in SISTEMAS}
    t0 = time.perf_counter()
    for i, c in enumerate(alvo):
        ps, ord_c = chunks[c.contrato], ordens[c.contrato]
        gold.append({p.ordem for p in ps if any(corpus.relevante(p, s) for s in c.spans)})

        sim_b = M[c.contrato] @ V_bruto[c.pergunta]
        sim_e = M[c.contrato] @ V_enxuto[c.pergunta]
        sb = bm25[c.contrato].pontuar(busca.tokenizar(c.pergunta))
        rd = np.empty(len(ord_c), dtype=np.float32)
        rb = np.empty(len(ord_c), dtype=np.float32)
        rd[np.argsort(-sim_e)] = np.arange(len(ord_c))
        rb[np.argsort(-sb)] = np.arange(len(ord_c))
        rrf = 1.0 / (RRF_K + rd) + 1.0 / (RRF_K + rb)

        for nome, s in (("denso_bruto", sim_b), ("denso_enxuto", sim_e),
                        ("bm25", sb), ("hibrido_rrf", rrf)):
            topo[nome].append([ord_c[j] for j in np.argsort(-s)[:kmax]])
        topo["primeiros"].append(ord_c[:kmax])
        topo["aleatorio"].append(rng.sample(ord_c, min(kmax, len(ord_c))))
        if i % 2000 == 0:
            print(f"  {i:,}/{len(alvo):,}", flush=True)
    dur = time.perf_counter() - t0
    validos = [i for i in range(len(alvo)) if gold[i]]
    print(f"avaliacao: {dur:.1f}s   consultas com gold: {len(validos):,}")

    def rec(s: str, k: int, idxs=None) -> tuple[int, int]:
        it = idxs if idxs is not None else validos
        return sum(1 for i in it if set(topo[s][i][:k]) & gold[i]), len(it)

    art: dict = {"n_consultas_respondiveis": len(alvo), "n_com_gold": len(validos),
                 "chunk": corpus.CHUNK, "sobreposicao": corpus.SOBREPOSICAO,
                 "semente": SEMENTE, "rrf_k": RRF_K,
                 "hnsw_usado_pelo_planner": False,
                 "recall": {}, "mcnemar": {}, "por_categoria": {}}

    print("\n" + "=" * 76)
    print(f"{'sistema':16s}" + "".join(f"{'recall@'+str(k):>14s}" for k in KS))
    print("=" * 76)
    for s in SISTEMAS:
        art["recall"][s] = {}
        linha = f"{s:16s}"
        for k in KS:
            ac, n = rec(s, k)
            lo, hi = wilson(ac, n)
            art["recall"][s][f"@{k}"] = {"acertos": ac, "n": n, "taxa": round(ac / n, 4),
                                         "ic95": [round(lo, 4), round(hi, 4)]}
            linha += f"{ac/n:>13.1%} "
        print(linha)

    print("\nMcNemar pareado:")
    for a, b_ in (("denso_enxuto", "bm25"), ("denso_enxuto", "denso_bruto"),
                  ("hibrido_rrf", "denso_enxuto")):
        for k in (5, 10):
            g = sum(1 for i in validos if set(topo[a][i][:k]) & gold[i]
                    and not set(topo[b_][i][:k]) & gold[i])
            p_ = sum(1 for i in validos if not set(topo[a][i][:k]) & gold[i]
                     and set(topo[b_][i][:k]) & gold[i])
            art["mcnemar"][f"{a}_x_{b_}@{k}"] = {"a_ganha": g, "b_ganha": p_, "p": mcnemar(g, p_)}
            print(f"  @{k:<3d} {a} x {b_}: {g} x {p_}  p={mcnemar(g, p_):.4g}")

    porcat: dict[str, list[int]] = defaultdict(list)
    for i in validos:
        porcat[alvo[i].categoria].append(i)
    venc = {"denso_enxuto": 0, "bm25": 0, "empate": 0}
    for cat, idxs in sorted(porcat.items()):
        linha = {s: round(rec(s, 5, idxs)[0] / len(idxs), 4)
                 for s in ("denso_enxuto", "bm25", "primeiros")}
        art["por_categoria"][cat] = {**linha, "n": len(idxs)}
        d, b2 = linha["denso_enxuto"], linha["bm25"]
        venc["denso_enxuto" if d > b2 else "bm25" if b2 > d else "empate"] += 1
    art["categorias_vencidas_em_recall5"] = venc
    print(f"\ncategorias (41) em recall@5 — denso_enxuto vence {venc['denso_enxuto']}, "
          f"bm25 vence {venc['bm25']}, empate {venc['empate']}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
