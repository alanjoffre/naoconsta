"""O agente: grafo LangGraph de três nós, e o terceiro é o que o projeto existe para defender.

    recuperar ──▶ decidir ──▶ verificar ──▶ (responde | não consta)

`verificar` é uma guarda **determinística de procedência**: se o agente afirma responder, a
citação tem de aparecer **literalmente** em um dos trechos recuperados. Se não aparecer, o texto
não veio do contrato — veio do modelo — e o grafo força a abstenção.

Isso é a ideia central do RodoQuery noutra forma. Lá, o vocabulário fechado não era *pedido* no
prompt, era **imposto pelo compilador**: spec inválida não compilava e virava abstenção. Aqui, o
que se impõe é a **origem do texto**, e a verificação é uma comparação de string — sem juiz-LLM,
sem modelo participando da régua que o mede.

Decisão de método declarada: **nada de structured outputs / JSON mode**. Forçar o schema resolveria
por decreto metade do que esta fase mede (quantas saídas o modelo emite malformadas, e o que ele
faz quando não sabe). A Fase 15 do RodoQuery mostrou que é exatamente aí que um modelo fraco
denuncia a própria incapacidade — e essa denúncia é dado, não ruído a ser suprimido.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal, TypedDict

PROMPT = """Você analisa contratos comerciais. Responda SOMENTE com base nos trechos fornecidos.

REGRAS:
1. Se a resposta estiver nos trechos, devolva a decisão "responde", o número do trecho e uma
   CITAÇÃO LITERAL, copiada caractere a caractere do trecho. Não parafraseie, não resuma.
2. Se os trechos NÃO contiverem a resposta, devolva "nao_consta". Isso é uma resposta correta e
   esperada: a maioria das perguntas sobre um contrato não tem resposta nele.
3. Não use conhecimento externo. Não deduza o que "provavelmente" o contrato diz.

Devolva APENAS um JSON, sem texto antes ou depois:
{{"decisao": "responde" ou "nao_consta", "trecho": número ou null,
  "citacao": "texto literal copiado do trecho, ou vazio"}}

TRECHOS DO CONTRATO:
{trechos}

Pergunta: {pergunta}"""


class Estado(TypedDict, total=False):
    pergunta: str
    contrato: str
    trechos: list[dict]
    bruto: str
    decisao: Literal["responde", "nao_consta"]
    trecho: int | None
    citacao: str
    json_malformado: bool
    guarda_barrou: bool
    motivo_guarda: str


@dataclass
class Metricas:
    """Contadores da execução. Existem para que a falha seja EXPLÍCITA, não silenciosa."""
    json_malformado: int = 0
    guarda_barrou: int = 0
    respondeu: int = 0
    absteve: int = 0
    motivos: dict[str, int] = field(default_factory=dict)


_JSON = re.compile(r"\{.*\}", re.S)


def _normalizar(t: str) -> str:
    """Compara ignorando espaço em branco e caixa.

    O modelo reproduz o trecho com quebras de linha diferentes o tempo todo; exigir igualdade byte
    a byte reprovaria citações honestas e inflaria a guarda. Normalizar espaço é o mínimo que
    mantém a checagem HONESTA — ela ainda reprova qualquer palavra que não esteja no contrato.
    """
    return re.sub(r"\s+", " ", t).strip().lower()


def extrair_json(bruto: str) -> dict | None:
    """O modelo enfeita a saída com prosa e cercas de markdown. Pegar o maior bloco {...}."""
    m = _JSON.search(bruto)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def montar_prompt(pergunta: str, trechos: list[dict]) -> str:
    corpo = "\n\n".join(f"[{t['id']}] {t['texto']}" for t in trechos)
    return PROMPT.format(trechos=corpo, pergunta=pergunta)


def verificar(estado: Estado) -> Estado:
    """A guarda. Só pode converter `responde` em `nao_consta`, nunca o contrário.

    Essa assimetria é deliberada e é o que torna a previsão nº 2 do pré-registro falsificável: a
    guarda NÃO PODE melhorar o lado respondível, então qualquer ganho tem de aparecer na abstenção.
    """
    if estado.get("decisao") != "responde":
        return estado
    cit = _normalizar(estado.get("citacao") or "")
    if len(cit) < 12:
        return {**estado, "decisao": "nao_consta", "guarda_barrou": True,
                "motivo_guarda": "citacao_vazia_ou_curta"}
    if not any(cit in _normalizar(t["texto"]) for t in estado["trechos"]):
        return {**estado, "decisao": "nao_consta", "guarda_barrou": True,
                "motivo_guarda": "citacao_ausente_do_contexto"}
    return estado


def decidir_do_bruto(bruto: str) -> Estado:
    """Parse + política de falha. JSON malformado NÃO vira abstenção silenciosa: vira abstenção
    ROTULADA, para que o número apareça no relatório em vez de se esconder dentro do acerto."""
    d = extrair_json(bruto)
    if d is None or d.get("decisao") not in ("responde", "nao_consta"):
        return {"bruto": bruto, "decisao": "nao_consta", "trecho": None, "citacao": "",
                "json_malformado": True}
    return {"bruto": bruto, "decisao": d["decisao"],
            "trecho": d.get("trecho") if isinstance(d.get("trecho"), int) else None,
            "citacao": str(d.get("citacao") or ""), "json_malformado": False}


def construir_grafo(recuperar, chamar_llm, com_guarda: bool = True):
    """Monta o StateGraph. `recuperar` e `chamar_llm` entram por injeção para que o grafo seja
    testável sem GPU, sem banco e sem rede — os testes exercitam a topologia, não o modelo."""
    from langgraph.graph import END, START, StateGraph

    def no_recuperar(estado: Estado) -> Estado:
        return {**estado, "trechos": recuperar(estado["contrato"], estado["pergunta"])}

    def no_decidir(estado: Estado) -> Estado:
        bruto = chamar_llm(montar_prompt(estado["pergunta"], estado["trechos"]))
        return {**estado, **decidir_do_bruto(bruto)}

    g = StateGraph(Estado)
    g.add_node("recuperar", no_recuperar)
    g.add_node("decidir", no_decidir)
    g.add_edge(START, "recuperar")
    g.add_edge("recuperar", "decidir")
    if com_guarda:
        g.add_node("verificar", verificar)
        g.add_edge("decidir", "verificar")
        g.add_edge("verificar", END)
    else:
        g.add_edge("decidir", END)
    return g.compile()
