"""Fase 3 — pontua as decisões congeladas. Sem juiz-LLM, sem GPU, sem rede.

Lê o artefato da Fase 2 e decide tudo por aritmética de intervalos. Pode ser re-executado à
vontade: re-pontuar não muda o que o modelo disse.

**A separação que o pré-registro exigiu.** O recall é 88,1%, então ~12% das consultas
respondíveis não têm o span no material entregue. Abster nesses casos é acerto **pelo motivo
errado** — o agente não tinha como responder. Por isso toda taxa aqui é reportada em dois
recortes: sobre TUDO e sobre o subconjunto RECUPERÁVEL (aquele em que a evidência estava lá).
Só o segundo mede o agente; o primeiro mede o sistema.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

ART = Path(__file__).resolve().parent / "reports" / "fase2"
SAIDA = Path(__file__).resolve().parent / "reports" / "fase3"


def wilson(a: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p, d = a / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n))


def _sobrepoe(a: list[int], b: list[int], fracao: float = 0.5) -> bool:
    """Interseção ≥ `fracao` do MENOR dos dois intervalos.

    Simétrico como na Fase 1: a citação pode ser mais curta que o span (frase dentro da cláusula)
    ou mais longa (o trecho de 400 caracteres, quando a busca literal falhou e o crédito foi para
    o trecho inteiro). Exigir contenção estrita num dos sentidos reprovaria metade dos acertos
    honestos; exigir 1 caractere aprovaria acaso.
    """
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return inter > 0 and inter >= fracao * min(a[1] - a[0], b[1] - b[0])


def recuperavel(r: dict) -> bool:
    """A evidência estava no material entregue ao agente?"""
    return any(_sobrepoe(t, s) for t in r["trechos_recuperados"] for s in r["spans_gold"])


def acertou(r: dict, sistema: str) -> bool:
    d = r[sistema]["decisao"]
    if not r["respondivel"]:
        return d == "nao_consta"
    if d != "responde" or not r["citacao_offsets"]:
        return False
    return any(_sobrepoe(r["citacao_offsets"], s) for s in r["spans_gold"])


def bloco(regs: list[dict], sistema: str, titulo: str) -> dict:
    resp = [r for r in regs if r["respondivel"]]
    nao = [r for r in regs if not r["respondivel"]]
    rec = [r for r in resp if recuperavel(r)]
    out = {}
    for nome, grupo in (("respondiveis", resp), ("respondiveis_recuperaveis", rec),
                        ("abstencao", nao)):
        a = sum(acertou(r, sistema) for r in grupo)
        lo, hi = wilson(a, len(grupo))
        out[nome] = {"acertos": a, "n": len(grupo),
                     "taxa": round(a / len(grupo), 4) if grupo else None,
                     "ic95": [round(lo, 4), round(hi, 4)]}
    total = sum(acertou(r, sistema) for r in regs)
    out["total"] = {"acertos": total, "n": len(regs), "taxa": round(total / len(regs), 4)}
    print(f"\n{titulo}")
    for nome in ("respondiveis", "respondiveis_recuperaveis", "abstencao", "total"):
        v = out[nome]
        ic = f"  IC95 [{v['ic95'][0]:.1%}; {v['ic95'][1]:.1%}]" if "ic95" in v else ""
        print(f"  {nome:28s} {v['acertos']:3d}/{v['n']:<3d} = {v['taxa']:6.1%}{ic}")
    return out


def main() -> int:
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(ART.glob("decisoes_*.json"))[-1]
    d = json.loads(caminho.read_text(encoding="utf-8"))
    regs = d["registros"]
    print(f"artefato: {caminho.name}   modelo: {d['modelo']}   k={d['k']}   n={len(regs)}")

    resp = [r for r in regs if r["respondivel"]]
    rec = [r for r in resp if recuperavel(r)]
    malformado = sum(r["json_malformado"] for r in regs)
    barrou = sum(r["com_guarda"]["guarda_barrou"] for r in regs)
    respondeu_sem = sum(r["sem_guarda"]["decisao"] == "responde" for r in regs)
    motivos = Counter(r["com_guarda"]["motivo"] for r in regs if r["com_guarda"]["motivo"])

    print(f"\nteto de recuperacao: {len(rec)}/{len(resp)} = {len(rec)/len(resp):.1%} "
          f"das respondiveis tinham a evidencia entregue")
    print(f"JSON malformado    : {malformado}/{len(regs)} = {malformado/len(regs):.1%}")
    print(f"o agente respondeu (sem guarda): {respondeu_sem}/{len(regs)}")
    print(f"a guarda BARROU    : {barrou}  ({barrou/max(respondeu_sem,1):.1%} das respostas)")
    for m, c in motivos.most_common():
        print(f"    {m}: {c}")

    art = {"artefato": caminho.name, "modelo": d["modelo"], "n": len(regs),
           "teto_recuperacao": round(len(rec) / len(resp), 4),
           "json_malformado": malformado, "guarda_barrou": barrou,
           "respondeu_sem_guarda": respondeu_sem, "motivos_guarda": dict(motivos),
           "sistemas": {}}
    for s, t in (("sem_guarda", "SEM guarda (o no `verificar` desligado)"),
                 ("com_guarda", "COM guarda de procedencia")):
        art["sistemas"][s] = bloco(regs, s, t)

    # pareado na abstencao: a guarda so pode converter responde->nao_consta
    nao = [r for r in regs if not r["respondivel"]]
    g = sum(1 for r in nao if acertou(r, "com_guarda") and not acertou(r, "sem_guarda"))
    p_ = sum(1 for r in nao if not acertou(r, "com_guarda") and acertou(r, "sem_guarda"))
    art["mcnemar_abstencao"] = {"guarda_ganha": g, "sem_guarda_ganha": p_, "p": mcnemar(g, p_)}
    delta = (art["sistemas"]["com_guarda"]["abstencao"]["taxa"]
             - art["sistemas"]["sem_guarda"]["abstencao"]["taxa"])
    art["delta_abstencao_pp"] = round(delta * 100, 2)
    print(f"\nMcNemar na abstencao: guarda {g} x {p_} sem-guarda   p={mcnemar(g, p_):.4g}")
    print(f"DELTA de abstencao: {delta*100:+.1f} pp")

    # ---- confronto com o pre-registro, item a item
    prev = {
        "1: guarda pega >=10% das respostas": (barrou / max(respondeu_sem, 1) >= 0.10,
                                               f"{barrou/max(respondeu_sem,1):.1%}"),
        "2: delta de abstencao >= 15 pp": (delta >= 0.15, f"{delta*100:+.1f} pp"),
        "3: sem_guarda abstem em < 40%": (
            art["sistemas"]["sem_guarda"]["abstencao"]["taxa"] < 0.40,
            f"{art['sistemas']['sem_guarda']['abstencao']['taxa']:.1%}"),
        "4: acuracia respondiveis <= 55%": (
            art["sistemas"]["com_guarda"]["respondiveis"]["taxa"] <= 0.55,
            f"{art['sistemas']['com_guarda']['respondiveis']['taxa']:.1%}"),
        "5: >=5% de JSON malformado": (malformado / len(regs) >= 0.05,
                                       f"{malformado/len(regs):.1%}"),
    }
    print("\n" + "=" * 64 + "\nCONFRONTO COM O PRE-REGISTRO\n" + "=" * 64)
    art["preregistro"] = {}
    for k, (ok, val) in prev.items():
        art["preregistro"][k] = {"confirmada": bool(ok), "medido": val}
        print(f"  {'CONFIRMADA' if ok else 'REFUTADA  '}  {k:36s} medido: {val}")

    SAIDA.mkdir(parents=True, exist_ok=True)
    alvo = SAIDA / f"pontuacao_{caminho.stem}.json"
    alvo.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {alvo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
