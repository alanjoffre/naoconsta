"""Fase 1d — valida o chunk candidato no CONJUNTO COMPLETO, contra o portao v2.

A varredura da Fase 1c rodou em 60 contratos, e a amostra e ~2,7 pp mais facil que o todo
(1200/200 da 81,5% la e 78,8% aqui). Portao nao se declara aberto com numero de amostra.

Portao v2: recall com ORCAMENTO DE 12.000 CARACTERES >= 85%, no conjunto completo.
"""
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from naoconsta import busca, corpus

CONFIGS = [(400, 75), (300, 60)]
ORCAMENTOS = (6_000, 12_000, 24_000)
PORTAO = ("recall_em_12000chars", 0.85)
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "validacao_completa.json"


def wilson(a: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p, d = a / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def main() -> int:
    _, consultas, textos = corpus.carregar()
    alvo = [c for c in consultas if c.respondivel]
    distintas = sorted({c.pergunta for c in alvo})
    VQ = dict(zip(distintas, busca.embutir([corpus.enxugar(q) for q in distintas]), strict=True))
    print(f"conjunto COMPLETO: {len(textos)} contratos, {len(alvo):,} consultas respondiveis")

    art: dict = {"portao_v2": {"metrica": PORTAO[0], "limiar": PORTAO[1]}, "configs": {}}
    for tam, sob in CONFIGS:
        corpus.CHUNK, corpus.SOBREPOSICAO, corpus.PASSO = tam, sob, tam - sob
        chunks = {n: corpus.fatiar(n, t) for n, t in textos.items()}
        total = sum(len(v) for v in chunks.values())
        print(f"\n--- {tam}/{sob}: {total:,} chunks ---", flush=True)

        t0 = time.perf_counter()
        M, feitos = {}, 0
        for n, ps in chunks.items():
            M[n] = busca.embutir([p.texto for p in ps])
            feitos += len(ps)
            if feitos % 20000 < len(ps):
                print(f"    {feitos:,}/{total:,} ({feitos/(time.perf_counter()-t0):.0f} ch/s)",
                      flush=True)
        dur = time.perf_counter() - t0

        k_orc = {o: max(1, o // tam) for o in ORCAMENTOS}
        ac = dict.fromkeys(ORCAMENTOS, 0)
        n_val = 0
        for c in alvo:
            ps = chunks[c.contrato]
            gold = {p.ordem for p in ps if any(corpus.relevante(p, s) for s in c.spans)}
            if not gold:
                continue
            n_val += 1
            topo = [ps[j].ordem for j in np.argsort(-(M[c.contrato] @ VQ[c.pergunta]))]
            for o, k in k_orc.items():
                ac[o] += bool(set(topo[:k]) & gold)

        r = {}
        for o in ORCAMENTOS:
            lo, hi = wilson(ac[o], n_val)
            r[f"recall_em_{o}chars"] = round(ac[o] / n_val, 4)
            r[f"ic95_em_{o}chars"] = [round(lo, 4), round(hi, 4)]
        passou = r[PORTAO[0]] >= PORTAO[1]
        art["configs"][f"{tam}/{sob}"] = {
            "n_chunks": total, "n_consultas": n_val, "segundos_embed": round(dur, 1),
            "chunks_por_segundo": round(total / dur, 1), "k_por_orcamento": k_orc,
            "portao_v2_passou": passou, **r}
        for o in ORCAMENTOS:
            ic = r[f"ic95_em_{o}chars"]
            print(f"  {o:6,} chars (k={k_orc[o]:3d}): {r[f'recall_em_{o}chars']:.1%} "
                  f"IC95 [{ic[0]:.1%}; {ic[1]:.1%}]")
        print(f"  PORTAO v2 (>= 85% em 12k chars): {'PASSOU' if passou else 'FECHADO'}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0 if any(c["portao_v2_passou"] for c in art["configs"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
