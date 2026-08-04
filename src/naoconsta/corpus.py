"""Corpus CUAD: carregar, fatiar em chunks e derivar o GOLD da recuperação.

Três decisões de método, todas medidas na Fase 1 (`reports/fase1/estrutura_consultas.json`) e
não escolhidas por gosto:

**Chunk de 1.200 caracteres.** O span mediano tem 196 caracteres e o p99 tem 1.330; um chunk de
1.200 preserva **98,55%** dos spans inteiros, contra 78,62% em 400 e 95,69% em 800. Passar para
2.000 levaria a 99,75% — +1,2 pp de cobertura ao custo de 67% mais texto por chunk, o que dilui a
similaridade e enche o contexto do agente. 1.200 é o joelho da curva, e a curva está no artefato.

**Sobreposição de 200.** Sem ela, um span que cai exatamente na fronteira fica partido ao meio nos
dois chunks e nenhum o contém. Com 200 (a mediana do span, arredondada), todo span de até 200
caracteres aparece inteiro em pelo menos um chunk.

**Busca com filtro por contrato.** O CUAD faz as MESMAS 41 perguntas a cada contrato — são 41
textos de consulta distintos repetidos até 510 vezes. Buscar "qual a lei aplicável?" no corpus
inteiro é uma pergunta mal-posta: a resposta certa depende de qual contrato se está revisando.
O índice guarda os ~26 mil chunks juntos (é o que um sistema real faz) e a consulta filtra por
contrato — o padrão multi-tenant de banco vetorial, não um atalho.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1200
SOBREPOSICAO = 200
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
