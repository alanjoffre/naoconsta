"""Auditoria de FIDELIDADE: cada número afirmado na documentação existe num artefato?

Um README bonito com número errado é pior que nenhum. Este script lê `reports/**` e confere
contra o que o README e os docs afirmam. Ele NÃO conserta nada — só denuncia.

Regra do projeto: se um número aparece no README, ou ele sai daqui, ou é retratado. Vale também
quando o número é contra mim — os 33% de acurácia e as 3 previsões refutadas são conferidos com o
mesmo rigor que o recall de 88,1%.

Portado do RodoQuery, onde essa trava pegou uma contradição real (o README afirmava 86,9% numa
linha e o artefato guardava 89,7%).
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent
R = REPO / "reports"
ok = falhas = 0


def _j(rel: str):
    p = R / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def checa(rotulo: str, obtido, esperado, tol: float = 0.0):
    global ok, falhas
    if obtido is None:
        print(f"  AUSENTE  {rotulo:54s} (artefato nao encontrado)")
        falhas += 1
        return
    bate = (abs(float(obtido) - float(esperado)) <= tol
            if isinstance(esperado, (int, float)) else obtido == esperado)
    if bate:
        print(f"  OK       {rotulo:54s} {obtido}")
        ok += 1
    else:
        print(f"  DIVERGE  {rotulo:54s} doc={esperado}  artefato={obtido}")
        falhas += 1


print("=== FASE 0: aptidao do corpus (o cabecalho do README) ===")
f0 = _j("fase0/aptidao_cuad.json")
if f0:
    m = f0["medidas"]
    checa("veredito (README diz GO)", f0["veredito"], "GO")
    checa("contratos (README diz 510)", m["n_contratos"], 510)
    checa("PDFs (README diz 510 — case-insensitive)", m["n_pdf"], 510)
    checa("perguntas (README diz 20.910)", m["n_perguntas"], 20_910)
    checa("sem resposta (README diz 14.208)", m["n_impossiveis"], 14_208)
    checa("taxa sem resposta (README diz 68,0%)", m["taxa_is_impossible"], 0.68, 0.001)
    checa("spans (README diz 13.823)", m["n_spans"], 13_823)
    checa("spans conferem (README diz 100%)", m["taxa_span_confere"], 1.0)
    checa("categorias (README diz 41)", m["n_categorias"], 41)
    checa("mediana de chars (README diz 33.425)", m["chars_mediana"], 33_425)

print("\n=== FASE 1: estrutura e recall ===")
e1 = _j("fase1/estrutura_consultas.json")
if e1:
    checa("perguntas DISTINTAS (README diz 41)", e1["n_textos_de_pergunta_distintos"], 41)
    checa("a mais repetida (doc diz 510x)", e1["pergunta_mais_repetida"], 510)
    checa("span mediano (doc diz 196)", e1["spans"]["mediana"], 196)
    checa("dispersao mediana (doc diz 0,04)", e1["dispersao_mediana_dos_spans"], 0.04, 0.005)

r1 = _j("fase1/recall.json")
if r1:
    rec = r1["recall"]
    checa("F1 denso_bruto @5 (README diz 56,3%)", rec["denso_bruto"]["@5"]["taxa"], 0.5632, 0.001)
    checa("F1 denso_enxuto @5 (README diz 65,3%)", rec["denso_enxuto"]["@5"]["taxa"], 0.6531, 0.001)
    checa("F1 bm25 @5 (README diz 62,0%)", rec["bm25"]["@5"]["taxa"], 0.6203, 0.001)
    checa("F1 hibrido @5 (README diz 67,4%)", rec["hibrido_rrf"]["@5"]["taxa"], 0.6744, 0.001)
    checa("F1 primeiros @5 (README diz 35,7%)", rec["primeiros"]["@5"]["taxa"], 0.3572, 0.001)
    checa("F1 aleatorio @5 (README diz 21,3%)", rec["aleatorio"]["@5"]["taxa"], 0.2131, 0.001)
    checa("F1 HNSW usado pelo planner? (doc diz NAO)", r1["hnsw_usado_pelo_planner"], False)

d1 = _j("fase1/diagnostico.json")
if d1:
    cos = d1["cosseno_medio_entre_perguntas"]
    checa("cosseno com preambulo (doc diz 0,735)", cos["original"], 0.735, 0.002)
    checa("cosseno sem preambulo (doc diz 0,594)", cos["enxuto"], 0.594, 0.002)

cm = _j("fase1/comparacao_modelos.json")
if cm:
    mm = cm["modelos"]
    checa("bge-m3 @10 (doc diz 76,1%)", mm["bge-m3"]["recall@10"], 0.761, 0.002)
    checa("nomic @10 na amostra (doc diz 81,5%)", mm["nomic-embed-text"]["recall@10"],
          0.815, 0.002)

vc = _j("fase1/validacao_completa.json")
if vc:
    c = vc["configs"]
    checa("PORTAO v2: 400/75 em 12k (README diz 88,1%)",
          c["400/75"]["recall_em_12000chars"], 0.8809, 0.001)
    checa("PORTAO v2: 400/75 passou?", c["400/75"]["portao_v2_passou"], True)
    checa("300/60 em 12k (doc diz 89,5%)", c["300/60"]["recall_em_12000chars"], 0.8954, 0.001)
    checa("chunks em 400/75 (doc diz 82.622)", c["400/75"]["n_chunks"], 82_622)

ix = _j("fase1/indexacao.json")
if ix:
    checa("indice servido: chunk (doc diz 400)", ix["chunk"], 400)
    checa("indice servido: sobreposicao (doc diz 75)", ix["sobreposicao"], 75)
    checa("indice servido: n_chunks (doc diz 82.622)", ix["n_chunks"], 82_622)

print("\n=== FASE 2/3: o agente ===")
p2 = _j("fase3/pontuacao_decisoes_qwen2.5_7b_n200.json")
if p2:
    s = p2["sistemas"]
    checa("F2 n (README diz 200)", p2["n"], 200)
    checa("F2 teto de recuperacao (doc diz 87%)", p2["teto_recuperacao"], 0.87, 0.005)
    checa("F2 sem guarda: respondiveis (README diz 33,0%)",
          s["sem_guarda"]["respondiveis"]["taxa"], 0.33, 0.001)
    checa("F2 sem guarda: recuperaveis (README diz 36,8%)",
          s["sem_guarda"]["respondiveis_recuperaveis"]["taxa"], 0.3678, 0.001)
    checa("F2 sem guarda: abstencao (README diz 90,0%)",
          s["sem_guarda"]["abstencao"]["taxa"], 0.90, 0.001)
    checa("F2 sem guarda: total (README diz 123/200)", s["sem_guarda"]["total"]["acertos"], 123)
    checa("F2 com guarda: abstencao (README diz 91,0%)",
          s["com_guarda"]["abstencao"]["taxa"], 0.91, 0.001)
    checa("F2 com guarda: total (README diz 124/200)", s["com_guarda"]["total"]["acertos"], 124)
    checa("F2 guarda barrou (doc diz 8)", p2["guarda_barrou"], 8)
    checa("F2 delta de abstencao (doc diz +1,0 pp)", p2["delta_abstencao_pp"], 1.0, 0.05)
    checa("F2 JSON malformado (doc diz 2)", p2["json_malformado"], 2)
    # As previsoes do pre-registro sao conferidas UMA A UMA: o veredito "3 de 5 refutadas"
    # e uma afirmacao do README como qualquer outra, e tem de sair do artefato.
    pr = p2["preregistro"]
    conf = sum(1 for v in pr.values() if v["confirmada"])
    checa("F2 previsoes CONFIRMADAS (README diz 2)", conf, 2)
    checa("F2 previsoes REFUTADAS (README diz 3)", len(pr) - conf, 3)
    checa("F2 a central (delta>=15pp) caiu?",
          pr["2: delta de abstencao >= 15 pp"]["confirmada"], False)

v1 = _j("fase2/decisoes_qwen2.5_7b_n200_GUARDA_V1.json")
if v1:
    barrou = sum(1 for r in v1["registros"] if r["com_guarda"]["guarda_barrou"])
    checa("F2 guarda V1 barrou (doc diz 13)", barrou, 13)

print("\n=== GROQ: a conta e os limites medidos ===")
gc = _j("fase2/groq_conta.json")
if gc:
    checa("modelos visiveis (doc diz 15)", gc["n_modelos"], 15)
gl = _j("fase2/groq_limites.json")
if gl and "llama-3.3-70b-versatile" in gl:
    checa("TPM medido no 70b (doc diz 12.000)",
          gl["llama-3.3-70b-versatile"].get("x-ratelimit-limit-tokens"), "12000")

print("\n=== LINKS RELATIVOS ===")
ruins = []
for md in sorted(list(REPO.glob("*.md")) + list((REPO / "docs").glob("*.md"))):
    for m in re.finditer(r"\]\((?!http|#)([^)#]+)", md.read_text(encoding="utf-8")):
        if not (md.parent / m.group(1)).resolve().exists():
            ruins.append(f"{md.name}: {m.group(1)}")
if ruins:
    for x in ruins:
        print(f"  QUEBRADO {x}")
    falhas += len(ruins)
else:
    print("  OK       0 links quebrados")
    ok += 1

print("\n=== CUSTO DE API ACUMULADO ===")
total = 0.0
for p in sorted(R.glob("fase*/*.json")):
    d = json.loads(p.read_text(encoding="utf-8"))
    c = (d.get("telemetria") or {}).get("custo_usd_total")
    if isinstance(c, (int, float)) and c:
        total += c
        print(f"  {p.parent.name}/{p.name:44s} US$ {c:.4f}")
print(f"  {'TOTAL':56s} US$ {total:.4f}")

print(f"\n{'=' * 74}\nOK: {ok}   DIVERGENCIAS/AUSENTES: {falhas}")
raise SystemExit(1 if falhas else 0)
