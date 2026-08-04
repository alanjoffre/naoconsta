"""Fase 1, passo 0 — a ESTRUTURA das perguntas, antes de desenhar a recuperação.

Existe porque escolher chunk, embedding e escopo de busca sem olhar a forma do dado é chutar. E
porque uma suspeita precisa virar número: o CUAD parece fazer as MESMAS 41 perguntas a cada
contrato. Se for isso, o conjunto de consultas distintas é 41, não 20.910 — e reportar
"20.910 consultas" seria inflar o experimento por descuido.

Mede, sem opinar:
  1. quantos TEXTOS de pergunta distintos existem de fato;
  2. o tamanho dos spans de resposta (decide o chunk: span que não cabe no chunk é irrecuperável);
  3. quantos spans por pergunta e quão espalhados no documento;
  4. a taxa de `is_impossible` POR categoria (se for uniforme, o eixo da recusa é homogêneo;
     se for concentrada, há categorias que quase nunca existem e isso muda a leitura).
"""
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path.home() / "dados" / "cuad" / "CUAD_v1"
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "estrutura_consultas.json"
# Tamanhos candidatos de chunk (caracteres). O critério é: o span CABE inteiro num chunk?
CANDIDATOS_CHUNK = (400, 800, 1200, 2000, 3000)


def main() -> int:
    bruto = json.loads((RAIZ / "CUAD_v1.json").read_text(encoding="utf-8"))

    textos_pergunta: Counter = Counter()
    por_categoria: dict[str, dict] = defaultdict(lambda: {"total": 0, "impossiveis": 0})
    spans_len: list[int] = []
    spans_por_pergunta: list[int] = []
    dispersao: list[float] = []          # (fim do último span - início do primeiro) / len(contrato)
    n_contratos = 0

    for doc in bruto["data"]:
        for par in doc["paragraphs"]:
            n_contratos += 1
            ctx_len = len(par["context"])
            for qa in par["qas"]:
                cat = qa["id"].rsplit("__", 1)[-1]
                textos_pergunta[qa["question"]] += 1
                por_categoria[cat]["total"] += 1
                if qa.get("is_impossible"):
                    por_categoria[cat]["impossiveis"] += 1
                    continue
                resp = qa.get("answers") or []
                spans_por_pergunta.append(len(resp))
                for a in resp:
                    spans_len.append(len(a["text"]))
                if len(resp) > 1 and ctx_len:
                    ini = min(a["answer_start"] for a in resp)
                    fim = max(a["answer_start"] + len(a["text"]) for a in resp)
                    dispersao.append((fim - ini) / ctx_len)

    sl = sorted(spans_len)

    def pct(v: list[int], p: float) -> int:
        return v[min(len(v) - 1, int(len(v) * p))] if v else 0

    cabe = {c: round(sum(1 for s in sl if s <= c) / len(sl), 4) for c in CANDIDATOS_CHUNK}

    cats = {
        k: {**v, "taxa_impossivel": round(v["impossiveis"] / v["total"], 4)}
        for k, v in sorted(por_categoria.items())
    }
    taxas = sorted(c["taxa_impossivel"] for c in cats.values())

    art = {
        "n_contratos": n_contratos,
        "n_perguntas": sum(textos_pergunta.values()),
        "n_textos_de_pergunta_distintos": len(textos_pergunta),
        "pergunta_mais_repetida": textos_pergunta.most_common(1)[0][1],
        "spans": {
            "n": len(sl),
            "media": round(statistics.mean(sl), 1) if sl else 0,
            "mediana": pct(sl, 0.50), "p90": pct(sl, 0.90),
            "p99": pct(sl, 0.99), "max": sl[-1] if sl else 0,
        },
        "spans_por_pergunta_respondivel": {
            "media": round(statistics.mean(spans_por_pergunta), 2) if spans_por_pergunta else 0,
            "max": max(spans_por_pergunta) if spans_por_pergunta else 0,
        },
        "dispersao_mediana_dos_spans": (
            round(statistics.median(dispersao), 3) if dispersao else None
        ),
        "fracao_de_spans_que_cabem_no_chunk": cabe,
        "categorias": cats,
        "taxa_impossivel_min": taxas[0],
        "taxa_impossivel_mediana": taxas[len(taxas) // 2],
        "taxa_impossivel_max": taxas[-1],
    }

    print("=" * 76)
    print("FASE 1 — ESTRUTURA DAS CONSULTAS (antes de desenhar a recuperacao)")
    print("=" * 76)
    print(f"\ncontratos                     : {art['n_contratos']}")
    print(f"perguntas (pares contrato x Q) : {art['n_perguntas']:,}")
    print(f"TEXTOS de pergunta DISTINTOS   : {art['n_textos_de_pergunta_distintos']}")
    print(f"  -> a mais repetida aparece   : {art['pergunta_mais_repetida']}x")
    s = art["spans"]
    print(f"\nspans: n={s['n']:,}  media={s['media']}  mediana={s['mediana']}  "
          f"p90={s['p90']}  p99={s['p99']}  max={s['max']:,} caracteres")
    print(f"spans por pergunta respondivel : media {art['spans_por_pergunta_respondivel']['media']}"
          f", max {art['spans_por_pergunta_respondivel']['max']}")
    print(f"dispersao mediana no documento : {art['dispersao_mediana_dos_spans']}")
    print("\nfracao de spans que CABEM inteiros num chunk de N caracteres:")
    for c, f in cabe.items():
        print(f"  {c:5d} chars -> {f:.2%}")
    print(f"\ntaxa de is_impossible por categoria (41): min {art['taxa_impossivel_min']:.1%}  "
          f"mediana {art['taxa_impossivel_mediana']:.1%}  max {art['taxa_impossivel_max']:.1%}")
    extremos = sorted(cats.items(), key=lambda kv: kv[1]["taxa_impossivel"])
    print("  mais RESPONDIDAS :", ", ".join(f"{k} {v['taxa_impossivel']:.0%}"
                                            for k, v in extremos[:3]))
    print("  mais AUSENTES    :", ", ".join(f"{k} {v['taxa_impossivel']:.0%}"
                                            for k, v in extremos[-3:]))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
