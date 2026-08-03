"""Fase 0 de Dados — crivo de aptidão do CUAD, com go/no-go ANTES de construir qualquer coisa.

Disciplina herdada do RodoQuery: trocar de base no início custa um dia; descobrir no fim que a
base não sustenta a tese custa o projeto. Os critérios abaixo estão declarados ANTES de olhar o
dado, para que o veredito não seja escrito depois de ver o resultado.

A tese que este projeto quer medir: **num corpus onde a maioria das perguntas NÃO tem resposta,
o eixo que discrimina um agente de RAG é a RECUSA, não a acurácia.** É o achado do RodoQuery
(abstenção discrimina onde a acurácia satura) levado para outro domínio e outra stack.

Por isso o critério nº 3 é o que manda: se a taxa de `is_impossible` for baixa, o corpus não
serve para esta tese e é melhor saber agora.
"""
import json
import re
import statistics
from collections import Counter
from pathlib import Path

RAIZ = Path.home() / "dados" / "cuad" / "CUAD_v1"
SAIDA = Path(__file__).resolve().parent / "reports" / "fase0" / "aptidao_cuad.json"

# ---------------------------------------------------------------- critérios, declarados antes
CRITERIOS = {
    "1_volume_contratos":   ("≥ 300 contratos com texto extraído",
                             lambda m: m["n_contratos"] >= 300),
    "2_volume_perguntas":   ("≥ 5.000 perguntas rotuladas", lambda m: m["n_perguntas"] >= 5_000),
    "3_recusa_e_maioria":   ("≥ 50% das perguntas SEM resposta (o eixo da tese)",
                             lambda m: m["taxa_is_impossible"] >= 0.50),
    "4_gold_verificavel":   ("≥ 99% dos spans batem com o texto no offset declarado",
                             lambda m: m["taxa_span_confere"] >= 0.99),
    "5_gold_humano":        ("rótulo é humano, não de máquina", lambda m: m["gold_humano"]),
    "6_licenca_permissiva": ("licença permite uso em portfólio público", lambda m: m["licenca_ok"]),
    "7_texto_substancial":  ("mediana ≥ 10.000 caracteres por contrato (RAG faz sentido)",
                             lambda m: m["chars_mediana"] >= 10_000),
}


def medir() -> dict:
    m: dict = {}

    # ---- inventário de arquivos
    # `rglob("*.pdf")` é CASE-SENSITIVE e 311 dos 510 arquivos vêm com `.PDF` maiúsculo: a
    # primeira versão deste crivo contou 199 e teria publicado uma subcontagem de 61%. Contar
    # por sufixo normalizado, e conferir contra o ZIP (ver `_verificar_fase0.sh`).
    ext: Counter = Counter(p.suffix.lower() for p in RAIZ.rglob("*") if p.is_file())
    m["n_pdf"] = ext[".pdf"]
    m["n_txt"] = ext[".txt"]
    m["n_xlsx_relatorios_de_label"] = ext[".xlsx"]

    # ---- CUAD_v1.json (formato SQuAD 2.0)
    bruto = json.loads((RAIZ / "CUAD_v1.json").read_text(encoding="utf-8"))
    m["versao_declarada"] = bruto.get("version")

    contratos, perguntas, impossiveis, spans_ok, spans_total = [], 0, 0, 0, 0
    categorias: Counter = Counter()
    resp_por_pergunta: list[int] = []

    for doc in bruto["data"]:
        for par in doc["paragraphs"]:
            ctx = par["context"]
            contratos.append({"titulo": doc["title"], "chars": len(ctx)})
            for qa in par["qas"]:
                perguntas += 1
                # a categoria vem no fim do id: "<contrato>__<Categoria>"
                cat = qa["id"].rsplit("__", 1)[-1] if "__" in qa["id"] else "?"
                categorias[cat] += 1
                if qa.get("is_impossible"):
                    impossiveis += 1
                    continue
                resp = qa.get("answers") or []
                resp_por_pergunta.append(len(resp))
                for a in resp:
                    spans_total += 1
                    ini = a["answer_start"]
                    if ctx[ini:ini + len(a["text"])] == a["text"]:
                        spans_ok += 1

    chars = sorted(c["chars"] for c in contratos)
    m["n_contratos"] = len(contratos)
    m["n_contratos_distintos"] = len({c["titulo"] for c in contratos})
    m["n_perguntas"] = perguntas
    m["n_impossiveis"] = impossiveis
    m["n_respondiveis"] = perguntas - impossiveis
    m["taxa_is_impossible"] = round(impossiveis / perguntas, 4) if perguntas else 0.0
    m["n_spans"] = spans_total
    m["taxa_span_confere"] = round(spans_ok / spans_total, 4) if spans_total else 0.0
    m["n_categorias"] = len(categorias)
    m["categorias_top"] = categorias.most_common(5)
    m["perguntas_por_contrato"] = round(perguntas / len(contratos), 1) if contratos else 0
    m["spans_por_pergunta_respondivel"] = (
        round(statistics.mean(resp_por_pergunta), 2) if resp_por_pergunta else 0
    )
    m["chars_total"] = sum(chars)
    m["chars_mediana"] = chars[len(chars) // 2] if chars else 0
    m["chars_min"] = chars[0] if chars else 0
    m["chars_max"] = chars[-1] if chars else 0
    # ~4 chars/token é otimista para texto jurídico; serve de ordem de grandeza, e está rotulado.
    m["tokens_estimados_corpus"] = round(m["chars_total"] / 4)

    # ---- README: licença e proveniência do rótulo
    readme = (RAIZ / "CUAD_v1_README.txt").read_text(encoding="utf-8", errors="replace")
    # Citar a linha que de fato AFIRMA a licença — a 1ª versão casava "License Grant" (um tipo de
    # cláusula do corpus) e imprimia um trecho que não tinha nada a ver com licenciamento.
    m["licenca_ok"] = bool(re.search(r"licensed under.{0,80}CC BY 4\.0", readme, re.I | re.S))
    m["licenca_trecho"] = next(
        (ln.strip() for ln in readme.splitlines()
         if re.search(r"licensed under|creative commons", ln, re.I)), None
    )
    # "gold humano" só é afirmado se o README descrever o PROCESSO de anotação, não só citar
    # advogados de passagem.
    m["gold_humano"] = bool(re.search(r"law students? (attended|conducted)", readme, re.I))
    m["anotadores_trecho"] = next(
        (ln.strip()[:180] for ln in readme.splitlines()
         if re.search(r"law students? (attended|conducted)", ln, re.I)), None
    )
    return m


def main() -> int:
    m = medir()

    print("=" * 78)
    print("FASE 0 DE DADOS — CUAD (Contract Understanding Atticus Dataset)")
    print("=" * 78)
    print("\nfonte: Zenodo/Atticus Project (oficial, nao espelho)   "
          f"versao: {m['versao_declarada']}")
    print("\n--- inventario ---")
    print(f"  contratos (paragraphs)      : {m['n_contratos']}  "
          f"({m['n_contratos_distintos']} titulos distintos)")
    print(f"  PDFs originais              : {m['n_pdf']}")
    print(f"  TXTs                        : {m['n_txt']}")
    print(f"  relatorios .xlsx de label   : {m['n_xlsx_relatorios_de_label']}")
    print("\n--- perguntas ---")
    print(f"  total                       : {m['n_perguntas']:,}")
    print(f"  SEM resposta (is_impossible): {m['n_impossiveis']:,}  "
          f"({m['taxa_is_impossible']:.1%})")
    print(f"  com resposta                : {m['n_respondiveis']:,}")
    print(f"  categorias de clausula      : {m['n_categorias']}")
    print(f"  perguntas por contrato      : {m['perguntas_por_contrato']}")
    print(f"  spans por pergunta respondivel: {m['spans_por_pergunta_respondivel']}")
    print("\n--- gold ---")
    print(f"  spans totais                : {m['n_spans']:,}")
    print(f"  spans que CONFEREM no offset: {m['taxa_span_confere']:.2%}")
    print(f"  anotador                    : {m['anotadores_trecho']}")
    print(f"  licenca                     : {m['licenca_trecho']}")
    print("\n--- texto ---")
    print(f"  caracteres totais           : {m['chars_total']:,}  "
          f"(~{m['tokens_estimados_corpus']:,} tokens, rotulo: chars/4)")
    print(f"  por contrato  min/mediana/max: {m['chars_min']:,} / "
          f"{m['chars_mediana']:,} / {m['chars_max']:,}")

    print("\n" + "=" * 78)
    print("CRITERIOS (declarados ANTES de olhar o dado)")
    print("=" * 78)
    reprovados = []
    for chave, (texto, teste) in CRITERIOS.items():
        try:
            passou = bool(teste(m))
        except Exception:                                          # noqa: BLE001
            passou = False
        print(f"  {'PASSA ' if passou else 'FALHA '} {chave:24s} {texto}")
        if not passou:
            reprovados.append(chave)

    veredito = "GO" if not reprovados else "NO-GO"
    detalhe = f"   (reprovou em: {', '.join(reprovados)})" if reprovados else ""
    print(f"\nVEREDITO: {veredito}{detalhe}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(
        {"veredito": veredito, "reprovados": reprovados,
         "criterios": {k: v[0] for k, v in CRITERIOS.items()}, "medidas": m},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artefato: {SAIDA}")
    return 0 if veredito == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
