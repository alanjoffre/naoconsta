"""Testes do servidor MCP.

A lógica é testada com um índice FALSO injetado no cache — sem Postgres, sem Ollama, sem corpus.
O que se exercita é o contrato das ferramentas (validação, escopo, formato de saída), não a
qualidade da recuperação, que já foi medida na Fase 1.
"""
import json

import numpy as np
import pytest

from naoconsta import corpus, servidor_mcp


@pytest.fixture(autouse=True)
def indice_falso(monkeypatch):
    """Dois contratos, vetores unitários em direções conhecidas — a ordem do topo é previsível."""
    ps_a = [corpus.Pedaco("contrato_a", i, i * 400, (i + 1) * 400, f"trecho A{i}")
            for i in range(3)]
    ps_b = [corpus.Pedaco("contrato_b", 0, 0, 400, "trecho B0")]
    idx = servidor_mcp.Indice(
        chunks={"contrato_a": ps_a, "contrato_b": ps_b},
        matriz={"contrato_a": np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32),
                "contrato_b": np.array([[1, 0]], dtype=np.float32)},
        ordens={"contrato_a": [0, 1, 2], "contrato_b": [0]},
    )
    # Guardar a função ORIGINAL: depois do `setattr`, `servidor_mcp.carregar_indice` é o lambda,
    # que não tem `cache_clear`. O teardown roda ANTES do monkeypatch desfazer, então limpar pelo
    # nome do módulo estoura com AttributeError — foi o que aconteceu na primeira versão.
    original = servidor_mcp.carregar_indice
    original.cache_clear()
    monkeypatch.setattr(servidor_mcp, "carregar_indice", lambda: idx)
    monkeypatch.setattr(servidor_mcp.busca, "embutir",
                        lambda ts, **kw: np.array([[1, 0]] * len(ts), dtype=np.float32))
    yield
    original.cache_clear()


def test_recupera_na_ordem_da_similaridade():
    r = servidor_mcp.recuperar("contrato_a", "qualquer", k=3)
    assert [t["ordem"] for t in r["trechos"]] == [0, 1, 2]
    assert r["trechos"][0]["similaridade"] == 1.0


def test_devolve_procedencia_em_cada_trecho():
    """Offsets e contrato são o que permite auditar a resposta contra o documento —
    um trecho sem procedência não serve para o propósito do servidor."""
    t = servidor_mcp.recuperar("contrato_a", "q", k=1)["trechos"][0]
    assert {"ordem", "inicio", "fim", "similaridade", "texto"} <= set(t)
    assert t["fim"] > t["inicio"]


def test_escopo_e_por_contrato():
    """As 41 perguntas do CUAD se repetem em todos os contratos: vazar de um para outro
    tornaria a resposta certa dependente do contrato errado."""
    r = servidor_mcp.recuperar("contrato_b", "q", k=10)
    assert r["contrato"] == "contrato_b"
    assert len(r["trechos"]) == 1


def test_contrato_desconhecido_falha_alto():
    with pytest.raises(ValueError, match="contrato desconhecido"):
        servidor_mcp.recuperar("nao_existe", "q")


@pytest.mark.parametrize("pedido,esperado", [(0, 1), (-5, 1), (3, 3), (999, 3)])
def test_k_e_limitado_nos_dois_extremos(pedido, esperado):
    """k=0 devolveria nada e k enorme devolveria o contrato inteiro, que é o modo de falha
    que a Fase 1b mediu: mais texto compra recall e paga em abstenção."""
    r = servidor_mcp.recuperar("contrato_a", "q", k=pedido)
    assert len(r["trechos"]) == esperado


def test_conta_os_caracteres_entregues():
    """O orçamento de texto é a unidade que a Fase 1 provou ser a justa — o cliente precisa
    dele para comparar configurações sem se enganar com `k`."""
    assert servidor_mcp.recuperar("contrato_a", "q", k=2)["caracteres_entregues"] == 800


def test_enxuga_a_pergunta_sem_o_cliente_pedir(monkeypatch):
    """`enxugar` vale +9,0 pp; exigir que o cliente o aplique seria entregar menos recall a
    quem não leu a Fase 1."""
    vistos = []
    monkeypatch.setattr(servidor_mcp.busca, "embutir",
                        lambda ts, **kw: (vistos.extend(ts),
                                          np.array([[1, 0]] * len(ts), dtype=np.float32))[1])
    servidor_mcp.recuperar("contrato_a", 'Highlight the parts (if any) of this contract '
                                         'related to "Governing Law" that should be reviewed '
                                         'by a lawyer. Details: which law?', k=1)
    assert "Highlight the parts" not in vistos[0]
    assert vistos[0].startswith("Governing Law")


def test_listar_filtra_por_prefixo():
    assert servidor_mcp.listar_contratos("contrato_a")["contratos"] == ["contrato_a"]
    assert servidor_mcp.listar_contratos()["n_total"] == 2


def test_estatisticas_declaram_o_teto():
    """O servidor precisa dizer que ~11,9% das respondíveis não têm evidência entregue —
    sem isso, quem consome os trechos lê abstenção como acerto."""
    e = servidor_mcp.estatisticas()
    assert e["recall_medido"]["recall"] == 0.8809
    assert "11,9%" in e["ressalva"]


def test_ferramentas_devolvem_json_serializavel():
    """As ferramentas MCP transportam texto: um numpy.float32 solto quebraria a serialização."""
    for nome, fn in servidor_mcp.FERRAMENTAS.items():
        r = fn("contrato_a", "q") if nome == "recuperar" else fn()
        json.dumps(r)  # levanta se houver tipo não serializável
