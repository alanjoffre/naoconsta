"""Testes do grafo e da guarda de procedência.

Rodam sem GPU, sem banco e sem rede: `recuperar` e `chamar_llm` entram por injeção, então o que
se exercita é a TOPOLOGIA e a POLÍTICA, não o modelo. Um teste que precisa de LLM para rodar não
é teste, é experimento.
"""
import pytest

from naoconsta.agente import (
    blocos_contiguos,
    construir_grafo,
    decidir_do_bruto,
    extrair_json,
    montar_prompt,
    verificar,
)

TRECHOS = [
    {"id": 0, "texto": "This Agreement shall be governed by the laws of the State of Delaware."},
    {"id": 1, "texto": "The term of this Agreement is three (3) years from the Effective Date."},
]


def _estado(decisao, citacao, trecho=0):
    return {"pergunta": "q", "contrato": "c", "trechos": TRECHOS,
            "decisao": decisao, "trecho": trecho, "citacao": citacao}


# ---------------------------------------------------------------- extração de JSON
def test_extrai_json_puro():
    assert extrair_json('{"decisao": "nao_consta"}')["decisao"] == "nao_consta"


def test_extrai_json_cercado_de_prosa_e_markdown():
    bruto = 'Claro! Aqui está:\n```json\n{"decisao": "responde", "trecho": 1}\n```\nEspero ajudar.'
    assert extrair_json(bruto)["trecho"] == 1


@pytest.mark.parametrize("bruto", ["", "sem json aqui", "{quebrado", '["lista"]'])
def test_json_invalido_vira_None(bruto):
    assert extrair_json(bruto) is None


def test_json_malformado_vira_abstencao_ROTULADA():
    """Falha de parse não pode virar abstenção silenciosa: se virar, o número se esconde
    dentro do acerto e o relatório mente sem que ninguém perceba."""
    e = decidir_do_bruto("o modelo divagou")
    assert e["decisao"] == "nao_consta"
    assert e["json_malformado"] is True


def test_decisao_fora_do_vocabulario_tambem_e_malformada():
    assert decidir_do_bruto('{"decisao": "talvez"}')["json_malformado"] is True


# ---------------------------------------------------------------- a guarda
def test_guarda_aceita_citacao_literal():
    e = verificar(_estado("responde", "governed by the laws of the State of Delaware"))
    assert e["decisao"] == "responde"
    assert not e.get("guarda_barrou")


def test_guarda_tolera_espaco_e_caixa_diferentes():
    """O modelo reformata quebras de linha o tempo todo; exigir igualdade byte a byte reprovaria
    citação honesta e INFLARIA a guarda — o que faria a Fase 2 parecer melhor do que é."""
    e = verificar(_estado("responde", "GOVERNED  BY\n THE LAWS of the State of Delaware"))
    assert e["decisao"] == "responde"


def test_guarda_barra_citacao_inventada():
    e = verificar(_estado("responde", "governed by the laws of the State of California"))
    assert e["decisao"] == "nao_consta"
    assert e["motivo_guarda"] == "citacao_ausente_do_contexto"


def test_guarda_barra_citacao_vazia_ou_curta():
    assert verificar(_estado("responde", ""))["motivo_guarda"] == "citacao_vazia_ou_curta"
    assert verificar(_estado("responde", "Delaware"))["motivo_guarda"] == "citacao_vazia_ou_curta"


def test_guarda_e_ASSIMETRICA_nunca_cria_resposta():
    """Só converte responde→nao_consta. É isso que torna a previsão 2 do pré-registro
    falsificável: a guarda não pode melhorar o lado respondível."""
    e = verificar(_estado("nao_consta", "qualquer coisa inventada"))
    assert e["decisao"] == "nao_consta"
    assert not e.get("guarda_barrou")


# ---------------------------------------------------------------- citação através de trechos
# Dois trechos CONTÍGUOS de um contrato (o segundo começa onde o primeiro termina).
CONTIGUOS = [
    {"id": 0, "inicio": 0, "fim": 60,
     "texto": "The initial term of this Agreement shall be for a period of "},
    {"id": 1, "inicio": 60, "fim": 118,
     "texto": "five (5) years from the date first set forth above hereto."},
]


def test_guarda_aceita_citacao_QUE_ATRAVESSA_trechos_adjacentes():
    """O defeito medido no piloto: com chunks de 400, toda citação maior que 400 era barrada
    POR CONSTRUÇÃO. Dos 13 barrados, 4 atravessavam trechos vizinhos e 3 acertavam o gold."""
    e = {"trechos": CONTIGUOS, "decisao": "responde", "trecho": 0,
         "citacao": "for a period of five (5) years from the date"}
    assert verificar(e)["decisao"] == "responde"


def test_guarda_ainda_barra_invencao_mesmo_com_fusao():
    """A fusão não pode virar frouxidão: texto que não está em lugar nenhum segue reprovado."""
    e = {"trechos": CONTIGUOS, "decisao": "responde", "trecho": 0,
         "citacao": "for a period of ten (10) years from the date"}
    assert verificar(e)["decisao"] == "nao_consta"


def test_blocos_nao_duplicam_a_sobreposicao():
    sobrepostos = [
        {"id": 0, "inicio": 0, "fim": 20, "texto": "The quick brown fox "},
        {"id": 1, "inicio": 15, "fim": 35, "texto": "fox jumps over lazy "},
    ]
    b = blocos_contiguos(sobrepostos)
    assert len(b) == 1
    assert b[0].count("fox") == 1, "a sobreposição foi remontada duas vezes"


def test_trechos_separados_nao_sao_fundidos():
    """Trechos distantes no contrato NÃO formam texto contínuo — fundi-los deixaria passar
    citação costurada de partes que o agente viu, mas que não são vizinhas no documento."""
    distantes = [
        {"id": 0, "inicio": 0, "fim": 20, "texto": "governed by Delaware"},
        {"id": 1, "inicio": 9000, "fim": 9020, "texto": " law and equity."},
    ]
    assert len(blocos_contiguos(distantes)) == 2
    e = {"trechos": distantes, "decisao": "responde",
         "citacao": "governed by Delaware law and equity."}
    assert verificar(e)["decisao"] == "nao_consta"


# ---------------------------------------------------------------- prompt e grafo
def test_prompt_numera_os_trechos_e_termina_na_pergunta():
    p = montar_prompt("Qual a lei aplicável?", TRECHOS)
    assert "[0] This Agreement" in p and "[1] The term" in p
    assert p.rstrip().endswith("Qual a lei aplicável?")


def _grafo(resposta_llm, com_guarda):
    return construir_grafo(lambda c, q: TRECHOS, lambda p: resposta_llm, com_guarda=com_guarda)


def test_grafo_com_guarda_barra_alucinacao_ponta_a_ponta():
    bruto = '{"decisao":"responde","trecho":0,"citacao":"laws of the State of California"}'
    r = _grafo(bruto, True).invoke({"pergunta": "q", "contrato": "c"})
    assert r["decisao"] == "nao_consta" and r["guarda_barrou"] is True


def test_grafo_SEM_guarda_deixa_a_alucinacao_passar():
    """O contrafactual que dá sentido à comparação da fase: sem o nó, a mesma saída passa."""
    bruto = '{"decisao":"responde","trecho":0,"citacao":"laws of the State of California"}'
    r = _grafo(bruto, False).invoke({"pergunta": "q", "contrato": "c"})
    assert r["decisao"] == "responde"


def test_grafo_preserva_resposta_legitima():
    bruto = ('{"decisao":"responde","trecho":0,'
             '"citacao":"governed by the laws of the State of Delaware"}')
    r = _grafo(bruto, True).invoke({"pergunta": "q", "contrato": "c"})
    assert r["decisao"] == "responde" and not r.get("guarda_barrou")
