"""Fase 1c — o chunk de 1.200 e a restricao que prende o recall?

A Fase 1 escolheu 1.200/200 por um criterio declarado (preserva 98,55% dos spans inteiros) — mas
"preservar o span" e "ser recuperavel" nao sao a mesma coisa. Chunk maior cobre mais texto por
posicao no ranking: em @10, dez chunks de 3.000 varrem 30 mil caracteres contra 12 mil de 1.200.
Se o gargalo for cobertura, isso aparece aqui.

CUIDADO DECLARADO: o gold MUDA com o chunk (as fronteiras mudam quais pedacos sao relevantes),
entao o recall e comparavel entre tamanhos mas a unidade nao e a mesma. Por isso a tabela reporta
tambem quantos chunks por contrato e quanto texto cada k varre — sem isso, chunk maior "ganha"
por construcao e o numero vira armadilha.
"""
import json
import time
from pathlib import Path

import numpy as np

from naoconsta import busca, corpus

CONFIGS = ((300, 60), (400, 75), (600, 100), (800, 150), (1200, 200), (2000, 300), (3000, 400))
KS = (1, 5, 10)
# Orçamentos de TEXTO, em caracteres. Comparar `recall@10` entre chunks de tamanhos diferentes é
# comparar coisas diferentes: em 3.000, dez chunks varrem 30 mil caracteres — ~90% do contrato
# mediano (33.425). O recall sobe porque devolveu quase tudo, não porque achou melhor. Com
# orçamento fixo, cada configuração recebe o k que cabe, e a comparação passa a ser justa.
ORCAMENTOS = (6_000, 12_000, 24_000)
N_CONTRATOS = 60
SEMENTE = 20260803
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "varredura_chunk.json"


def main() -> int:
    import random
    _, consultas, textos = corpus.carregar()
    rng = random.Random(SEMENTE)
    amostra = sorted(rng.sample(sorted(textos), N_CONTRATOS))
    alvo = [c for c in consultas if c.respondivel and c.contrato in set(amostra)]
    distintas = sorted({c.pergunta for c in alvo})
    VQ = dict(zip(distintas, busca.embutir([corpus.enxugar(q) for q in distintas]), strict=True))
    print(f"amostra: {len(amostra)} contratos, {len(alvo):,} consultas respondiveis")

    art: dict = {"n_contratos": len(amostra), "semente": SEMENTE, "configs": {}}
    print(f"\n{'chunk/sobrep':>14s} {'chunks':>8s} {'ch/contrato':>12s} "
          + "".join(f"{'@'+str(k):>8s}" for k in KS) + f"{'chars@10':>10s}"
          + "   | recall com ORCAMENTO DE TEXTO fixo: "
          + "  ".join(f"{o//1000}k" for o in ORCAMENTOS))
    print("-" * 118)

    for tam, sob in CONFIGS:
        corpus.CHUNK, corpus.SOBREPOSICAO = tam, sob
        corpus.PASSO = tam - sob
        chunks = {n: corpus.fatiar(n, textos[n]) for n in amostra}
        total = sum(len(v) for v in chunks.values())

        t0 = time.perf_counter()
        M = {n: busca.embutir([p.texto for p in ps]) for n, ps in chunks.items()}
        dur = time.perf_counter() - t0

        # k que cabe em cada orçamento de texto (pelo menos 1).
        k_orc = {orc: max(1, orc // tam) for orc in ORCAMENTOS}
        acertos = dict.fromkeys(KS, 0)
        acertos_orc = dict.fromkeys(ORCAMENTOS, 0)
        n_val = 0
        for c in alvo:
            ps = chunks[c.contrato]
            gold = {p.ordem for p in ps if any(corpus.relevante(p, s) for s in c.spans)}
            if not gold:
                continue
            n_val += 1
            sim = M[c.contrato] @ VQ[c.pergunta]
            topo = [ps[j].ordem for j in np.argsort(-sim)]
            for k in KS:
                acertos[k] += bool(set(topo[:k]) & gold)
            for orc, k in k_orc.items():
                acertos_orc[orc] += bool(set(topo[:k]) & gold)

        r = {f"recall@{k}": round(acertos[k] / n_val, 4) for k in KS}
        ro = {f"recall_em_{orc}chars": round(acertos_orc[orc] / n_val, 4) for orc in ORCAMENTOS}
        art["configs"][f"{tam}/{sob}"] = {
            "n_chunks": total, "chunks_por_contrato": round(total / len(amostra), 1),
            "n_consultas_com_gold": n_val, "segundos_embed": round(dur, 1),
            "chars_varridos_em_k10": 10 * tam, "k_por_orcamento": k_orc, **r, **ro,
        }
        print(f"{tam:6d}/{sob:<7d} {total:8,} {total/len(amostra):12.1f} "
              + "".join(f"{r[f'recall@{k}']:>7.1%} " for k in KS)
              + f"{10*tam:>10,}   |"
              + "".join(f"{ro[f'recall_em_{o}chars']:>7.1%}(k={k_orc[o]})" for o in ORCAMENTOS))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
