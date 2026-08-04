"""Corpus CUAD: carregar, fatiar em chunks e derivar o GOLD da recuperação.

Três decisões de método, todas medidas na Fase 1 (`reports/fase1/estrutura_consultas.json`) e
não escolhidas por gosto:

**Chunk de 400 caracteres** — e a primeira versão usava 1.200, pelo motivo errado. O critério
original era "preservar o span inteiro": 1.200 preserva 98,55% deles contra 78,62% em 400. Mas
*preservar* e *recuperar* não são a mesma coisa. Medido com **orçamento de texto fixo** (o k que
cabe em 12.000 caracteres, para que todas as configurações entreguem a mesma quantidade de
evidência), a ordem se inverte monotonicamente:

    400/75    88,1%  (k=30)   <- adotado
   1200/200   78,8%  (k=10)   <- a escolha anterior
   3000/400   70,7%  (k=4)

São **+9,3 pp sem gastar um caractere a mais**. Comparar `recall@k` entre tamanhos diferentes é
comparar coisas diferentes — chunk grande "ganha" varrendo mais texto, não achando melhor. Ver
`docs/FASE1B_ALAVANCAS.md`.

Não se adotou 300/60 (89,5%, +1,4 pp) porque ele custa 35% mais vetores e entrega 40 fragmentos
onde 400/75 entrega 30 — e o agente da Fase 2 vai LER esses fragmentos. Que 40 cacos sejam piores
que 30 é **hipótese não medida**, e está declarada como tal.

**Sobreposição de 75.** Sem ela, um span na fronteira fica partido e nenhum chunk o contém. Com
75 (~⅕ do chunk), a regra de relevância de 50% do span continua alcançável nas bordas.

**Busca com filtro por contrato.** O CUAD faz as MESMAS 41 perguntas a cada contrato — são 41
textos de consulta distintos repetidos até 510 vezes. Buscar "qual a lei aplicável?" no corpus
inteiro é uma pergunta mal-posta: a resposta certa depende de qual contrato se está revisando.
O índice guarda os ~26 mil chunks juntos (é o que um sistema real faz) e a consulta filtra por
contrato — o padrão multi-tenant de banco vetorial, não um atalho.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CHUNK = 400
SOBREPOSICAO = 75
PASSO = CHUNK - SOBREPOSICAO


def raiz_cuad() -> Path:
    import os
    return Path(os.environ.get("NAOCONSTA_CUAD_DIR",
                               str(Path.home() / "dados" / "cuad" / "CUAD_v1")))


@dataclass(frozen=True)
class Pedaco:
    contrato: str
    ordem: int
    inicio: int
    fim: int
    texto: str


@dataclass(frozen=True)
class Consulta:
    contrato: str
    categoria: str
    pergunta: str
    respondivel: bool
    spans: tuple[tuple[int, int], ...]   # (inicio, fim) em caracteres do contrato


_PREAMBULO = re.compile(
    r"^highlight the parts \(if any\) of this contract related to [\"“]?(.+?)[\"”]?\s*"
    r"that should be reviewed by a lawyer\.?\s*(details:)?\s*", re.I | re.S)


def enxugar(pergunta: str) -> str:
    """Tira o preâmbulo idêntico que abre as 41 perguntas do CUAD.

    Não é cosmética: **medido**, o cosseno médio entre perguntas DIFERENTES é 0,735 (máx 0,944)
    com o preâmbulo e 0,594 sem — o texto comum domina o vetor e as 41 consultas ficam quase
    colineares, então o denso não tem o que discriminar. O recall@5 sai de 56,3% para 65,3%.

    O BM25 não sofre com isso (pontua termo a termo), o que explica por que ele vencia o denso
    antes do conserto — e por que a conclusão se inverte depois.
    """
    m = _PREAMBULO.match(pergunta.strip())
    if not m:
        return pergunta
    tema, resto = m.group(1).strip(), pergunta[m.end():].strip()
    return f"{tema}. {resto}" if resto else tema


def fatiar(contrato: str, texto: str) -> list[Pedaco]:
    """Janela deslizante em caracteres. Determinística e sem dependência externa de propósito:
    um chunker 'esperto' (por sentença/cláusula) seria uma variável a mais entre o dado e o
    resultado, e a Fase 1 quer medir a RECUPERAÇÃO, não o chunker."""
    pedacos, i, ordem = [], 0, 0
    n = len(texto)
    while i < n:
        fim = min(i + CHUNK, n)
        pedacos.append(Pedaco(contrato, ordem, i, fim, texto[i:fim]))
        ordem += 1
        if fim == n:
            break
        i += PASSO
    return pedacos


def relevante(pedaco: Pedaco, span: tuple[int, int]) -> bool:
    """Um chunk é relevante para um span se **metade de um dos dois** está dentro do outro.

    A regra é simétrica de propósito, e cobre os dois regimes que o dado tem:
      - span curto (mediana 196): exige que ≥50% dele esteja no chunk — 1 caractere de
        interseção não vale nada, e sem esse piso o recall seria inflado por acaso;
      - span longo (até 3.884, 1,45% dos casos): não cabe em 1.200 por construção, então o
        critério que vale é o chunk estar dentro do span (≥50% do chunk coberto).
    """
    ini, fim = span
    inter = min(pedaco.fim, fim) - max(pedaco.inicio, ini)
    if inter <= 0:
        return False
    return inter >= 0.5 * (fim - ini) or inter >= 0.5 * (pedaco.fim - pedaco.inicio)


def carregar() -> tuple[list[Pedaco], list[Consulta], dict[str, str]]:
    """Devolve (chunks, consultas, textos dos contratos). Uma passada, sem estado global."""
    bruto = json.loads((raiz_cuad() / "CUAD_v1.json").read_text(encoding="utf-8"))
    pedacos: list[Pedaco] = []
    consultas: list[Consulta] = []
    textos: dict[str, str] = {}

    for doc in bruto["data"]:
        for par in doc["paragraphs"]:
            nome = doc["title"]
            textos[nome] = par["context"]
            pedacos.extend(fatiar(nome, par["context"]))
            for qa in par["qas"]:
                spans = tuple(
                    (a["answer_start"], a["answer_start"] + len(a["text"]))
                    for a in (qa.get("answers") or [])
                )
                consultas.append(Consulta(
                    contrato=nome,
                    categoria=qa["id"].rsplit("__", 1)[-1],
                    pergunta=qa["question"],
                    respondivel=not qa.get("is_impossible", False),
                    spans=spans,
                ))
    return pedacos, consultas, textos


def gold_por_consulta(pedacos: list[Pedaco], consulta: Consulta) -> set[int]:
    """Ordens dos chunks (dentro do contrato) que contam como acerto para esta consulta."""
    if not consulta.respondivel:
        return set()
    return {p.ordem for p in pedacos
            if p.contrato == consulta.contrato
            and any(relevante(p, s) for s in consulta.spans)}
