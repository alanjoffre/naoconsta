"""Fase 2 — roda os dois agentes (com e sem guarda) e grava as decisões, sem pontuar nada.

Separar EXECUÇÃO de PONTUAÇÃO é deliberado: as decisões ficam congeladas em disco e a Fase 3
pode ser re-pontuada quantas vezes for preciso sem gastar GPU nem mudar o que o modelo disse. Foi
assim que o RodoQuery conseguiu corrigir gold nas Fases 14/15 e re-pontuar as MESMAS predições.

Os dois sistemas veem exatamente o mesmo prompt e os mesmos trechos; a ÚNICA diferença é o nó
`verificar`. Por isso a chamada ao LLM é feita **uma vez** e a saída bruta alimenta os dois — se
eu chamasse duas vezes, a diferença entre os sistemas incluiria a variação do modelo, e a
comparação deixaria de ser pareada.
"""
import argparse
import json
import os
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from naoconsta import agente, busca, corpus, provedor

K = 30                     # 30 x 400 = 12.000 caracteres, o orçamento medido na Fase 1
MODELO = "qwen2.5:7b"
SAIDA = Path(__file__).resolve().parent / "reports" / "fase2"
SEMENTE = 20260803


def localizar(contrato_texto: str, citacao: str, trechos: list[dict]) -> tuple[int, int] | None:
    """Onde a citação cai no contrato, em offsets — para comparar com o span do gold.

    Tenta a busca literal primeiro; se falhar (o modelo reformatou espaços), procura dentro do
    trecho que ele citou e devolve o intervalo DO TRECHO. É uma aproximação declarada: nesse caso
    o crédito vai para o trecho inteiro (400 caracteres), não para a frase exata. Isso é
    GENEROSO com o agente, e está registrado como tal para não parecer rigor que não existe.
    """
    if not citacao:
        return None
    i = contrato_texto.find(citacao)
    if i >= 0:
        return (i, i + len(citacao))
    alvo = agente._normalizar(citacao)
    for t in trechos:
        if alvo and alvo in agente._normalizar(t["texto"]):
            return (t["inicio"], t["fim"])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="0 = tudo; senão, amostra estratificada")
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--provedor", default="ollama", choices=sorted(provedor.PROVEDORES))
    ap.add_argument("--teto-usd", type=float, default=1.00,
                    help="aborta SALVANDO o que ja foi pago, ao cruzar este gasto")
    ap.add_argument("--recomecar", action="store_true",
                    help="ignora o parcial e comeca do zero")
    args = ap.parse_args()
    provedor.carregar_env()
    chamar = provedor.obter(args.provedor)

    pedacos, consultas, textos = corpus.carregar()
    por_contrato: dict[str, list[corpus.Pedaco]] = defaultdict(list)
    for p in pedacos:
        por_contrato[p.contrato].append(p)
    for k in por_contrato:
        por_contrato[k].sort(key=lambda p: p.ordem)

    alvo = consultas
    if args.n:
        # Estratificado: metade respondível, metade abstenção. Amostrar sem estratificar daria
        # ~68% de abstenções e o lado respondível ficaria com n pequeno demais para dizer nada.
        rng = random.Random(SEMENTE)
        resp = [c for c in consultas if c.respondivel]
        nao = [c for c in consultas if not c.respondivel]
        alvo = rng.sample(resp, args.n // 2) + rng.sample(nao, args.n - args.n // 2)
        rng.shuffle(alvo)
    print(f"consultas: {len(alvo):,}  ({sum(c.respondivel for c in alvo)} respondiveis)  "
          f"provedor: {args.provedor}  modelo: {args.modelo}  k={K}")

    distintas = sorted({c.pergunta for c in alvo})
    VQ = dict(zip(distintas, busca.embutir([corpus.enxugar(q) for q in distintas]), strict=True))

    with psycopg.connect(busca.DSN) as con:
        register_vector(con)
        linhas = con.execute(
            "SELECT contrato, ordem, vetor FROM pedaco ORDER BY contrato, ordem").fetchall()
    M: dict[str, list] = defaultdict(list)
    for contrato, _ordem, v in linhas:
        M[contrato].append(np.asarray(v.to_list(), dtype=np.float32))
    Mat = {k: np.vstack(v) for k, v in M.items()}
    print(f"vetores do pgvector: {len(linhas):,}  (chunk={corpus.CHUNK}/{corpus.SOBREPOSICAO})")
    esperado = len(pedacos)
    if len(linhas) != esperado:
        print(f"  ABORTA: o indice tem {len(linhas):,} vetores e o corpus fatiado tem "
              f"{esperado:,}. O indice esta desatualizado — rode fase1_indexar.py.")
        return 2

    # ---- PARCIAL EM DISCO, uma linha por item, gravada NA HORA.
    # A rodada anterior gastou ~98 mil tokens da cota diaria do Groq, bateu no teto por DIA e
    # ABORTOU SEM SALVAR NADA. E exatamente a licao da Fase 21 do RodoQuery — "trava de orcamento
    # que joga fora trabalho ja pago e pior que nao ter trava" — que eu tinha registrada e nao
    # apliquei. Agora cada item e persistido assim que volta, e a rodada e RETOMAVEL.
    SAIDA.mkdir(parents=True, exist_ok=True)
    seguro = args.modelo.replace(":", "_").replace("/", "-")
    sufixo = f"_n{args.n}" if args.n else ""
    parcial = SAIDA / f"parcial_{seguro}{sufixo}.jsonl"
    if args.recomecar and parcial.exists():
        parcial.unlink()

    registros, telemetria = [], []
    if parcial.exists():
        for linha in parcial.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                d = json.loads(linha)
                registros.append(d["registro"])
                telemetria.append(d["telemetria"])
        print(f"retomando: {len(registros):,} itens ja no parcial ({parcial.name})")
    feitos = {(r["contrato"], r["categoria"]) for r in registros}
    gasto = sum(t.get("custo_usd") or 0 for t in telemetria)

    t0 = time.perf_counter()
    fp = parcial.open("a", encoding="utf-8")
    for i, c in enumerate(alvo):
        if (c.contrato, c.categoria) in feitos:
            continue
        if gasto >= args.teto_usd:
            print(f"\nTETO ATINGIDO: US$ {gasto:.4f} >= US$ {args.teto_usd:.2f}. "
                  f"{len(registros):,} itens SALVOS em {parcial.name}. "
                  f"Retome com o mesmo comando.")
            break
        ps = por_contrato[c.contrato]
        idx = np.argsort(-(Mat[c.contrato] @ VQ[c.pergunta]))[:K]
        trechos = [{"id": int(j), "texto": ps[j].texto,
                    "inicio": ps[j].inicio, "fim": ps[j].fim} for j in idx]

        try:
            bruto, tel = chamar(agente.montar_prompt(c.pergunta, trechos), args.modelo)
        except Exception as e:                                    # noqa: BLE001
            # Falha do provedor (limite diario, rede, 5xx) NAO pode levar junto o que ja foi
            # pago. Fecha o arquivo, diz onde parou e sai com codigo distinto de sucesso.
            fp.close()
            print(f"\nINTERROMPIDO em {len(registros):,} itens: {type(e).__name__}: "
                  f"{str(e)[:220]}")
            print(f"  o parcial esta salvo em {parcial}  — retome com o mesmo comando.")
            return 3
        telemetria.append(tel)
        gasto += tel.get("custo_usd") or 0
        base = agente.decidir_do_bruto(bruto)
        est = {"pergunta": c.pergunta, "contrato": c.contrato, "trechos": trechos, **base}
        com = agente.verificar(est)   # mesma saída bruta nos dois: comparação PAREADA de verdade

        loc = localizar(textos[c.contrato], base["citacao"], trechos)
        registro = {
            "contrato": c.contrato, "categoria": c.categoria, "respondivel": c.respondivel,
            "spans_gold": [list(s) for s in c.spans],
            # Os TEXTOS vão junto, não só os offsets. Sem eles não deu para diagnosticar por que
            # a guarda barrou 13 respostas no primeiro piloto — tive de inferir por offset. O
            # artefato custa ~2 MB e permite re-pontuar variantes da guarda sem tocar na GPU.
            "trechos_recuperados": [[t["inicio"], t["fim"]] for t in trechos],
            "trechos_texto": [t["texto"] for t in trechos],
            "json_malformado": base["json_malformado"],
            "citacao": base["citacao"], "citacao_offsets": list(loc) if loc else None,
            "sem_guarda": {"decisao": base["decisao"]},
            "com_guarda": {"decisao": com["decisao"],
                           "guarda_barrou": bool(com.get("guarda_barrou")),
                           "motivo": com.get("motivo_guarda")},
        }
        registros.append(registro)
        # grava JA, e força a ida ao disco: o valor de um parcial é ele sobreviver ao processo.
        fp.write(json.dumps({"registro": registro, "telemetria": tel}, ensure_ascii=False) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
        if i % 25 == 0:
            print(f"  {i:,}/{len(alvo):,}  ({len(registros)/(time.perf_counter()-t0):.2f} it/s)"
                  f"  gasto US$ {gasto:.4f}", flush=True)
    fp.close()

    nome = f"decisoes_{seguro}{sufixo}.json"

    def _soma(campo: str) -> float:
        return sum(t.get(campo) or 0 for t in telemetria)

    (SAIDA / nome).write_text(json.dumps({
        "modelo": args.modelo, "provedor": args.provedor, "k": K, "chunk": corpus.CHUNK,
        "sobreposicao": corpus.SOBREPOSICAO, "semente": SEMENTE,
        # A telemetria descreve o ARTEFATO, não a sessão que o produziu — lição da Fase 18 do
        # RodoQuery, onde re-pontuar predições congeladas publicava `custo_usd: 0`.
        "telemetria": {
            "modelo_efetivo": telemetria[0].get("modelo_efetivo") if telemetria else None,
            "custo_usd_total": round(_soma("custo_usd"), 6),
            "tokens_entrada": int(_soma("tokens_entrada")),
            "tokens_saida": int(_soma("tokens_saida")),
            "espera_por_limite_s": round(_soma("espera_por_limite_s"), 1),
        },
        "segundos": round(time.perf_counter() - t0, 1), "registros": registros,
    }, ensure_ascii=False), encoding="utf-8")
    t = json.loads((SAIDA / nome).read_text(encoding="utf-8"))["telemetria"]
    print(f"modelo efetivo: {t['modelo_efetivo']}   tokens: {t['tokens_entrada']:,} entrada / "
          f"{t['tokens_saida']:,} saida   custo: US$ {t['custo_usd_total']:.4f}   "
          f"espera por limite: {t['espera_por_limite_s']}s")
    print(f"\n{len(registros):,} decisoes em {time.perf_counter()-t0:.0f}s -> {SAIDA / nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
