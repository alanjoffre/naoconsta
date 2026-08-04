"""Testes do fatiamento, da regra de relevância e do `enxugar`.

Rodam sem o corpus: são sobre a lógica, não sobre os dados. O `enxugar` ganha teste porque ele
vale +9,0 pp de recall — código que carrega um resultado tem de ter alguém vigiando.
"""
import pytest

from naoconsta.corpus import CHUNK, PASSO, SOBREPOSICAO, Pedaco, enxugar, fatiar, relevante

PREAMBULO = ('Highlight the parts (if any) of this contract related to "Governing Law" '
             'that should be reviewed by a lawyer. Details: Which state/country\'s law '
             'governs the interpretation of the contract?')


def test_enxugar_remove_o_preambulo_e_preserva_o_discriminante():
    saida = enxugar(PREAMBULO)
    assert "Highlight the parts" not in saida
    assert "reviewed by a lawyer" not in saida
    assert saida.startswith("Governing Law")
    assert "state/country" in saida, "o 'Details:' é justamente a parte que discrimina"


def test_enxugar_e_idempotente():
    assert enxugar(enxugar(PREAMBULO)) == enxugar(PREAMBULO)


def test_enxugar_nao_mexe_em_pergunta_fora_do_molde():
    livre = "Qual é a lei aplicável a este contrato?"
    assert enxugar(livre) == livre


def test_enxugar_encolhe_de_verdade():
    assert len(enxugar(PREAMBULO)) < len(PREAMBULO) * 0.7


# ---------------------------------------------------------------- fatiamento
def test_fatiar_cobre_o_texto_inteiro():
    texto = "x" * 5000
    ps = fatiar("c", texto)
    assert ps[0].inicio == 0 and ps[-1].fim == len(texto)
    # todo caractere aparece em pelo menos um chunk
    coberto = set()
    for p in ps:
        coberto.update(range(p.inicio, p.fim))
    assert coberto == set(range(len(texto)))


def test_fatiar_sobrepoe_o_esperado():
    ps = fatiar("c", "x" * 5000)
    assert ps[1].inicio - ps[0].inicio == PASSO
    assert ps[0].fim - ps[1].inicio == SOBREPOSICAO


def test_texto_curto_vira_um_chunk_so():
    ps = fatiar("c", "x" * 10)
    assert len(ps) == 1 and ps[0].fim == 10


@pytest.mark.parametrize("n", [1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK])
def test_fatiar_nunca_devolve_chunk_vazio_nem_estoura(n):
    ps = fatiar("c", "x" * n)
    assert all(0 < p.fim - p.inicio <= CHUNK for p in ps)
    assert all(p.texto for p in ps)


# ---------------------------------------------------------------- relevância
def _p(ini, fim):
    return Pedaco("c", 0, ini, fim, "x" * (fim - ini))


def test_span_curto_inteiro_dentro_do_chunk_e_relevante():
    assert relevante(_p(0, 1200), (100, 300))


def test_encostar_de_raspao_nao_conta():
    # 10 caracteres de interseção num span de 200: sem piso, isso inflaria o recall.
    assert not relevante(_p(0, 1200), (1190, 1390))


def test_metade_do_span_basta():
    assert relevante(_p(0, 1200), (1100, 1300))


def test_span_maior_que_o_chunk_conta_se_engolir_o_chunk():
    """1,45% dos spans não cabem em 1.200 por construção — para eles, o critério que vale
    é o chunk estar DENTRO do span, senão seriam irrecuperáveis por definição."""
    assert relevante(_p(1000, 2200), (0, 3884))


def test_sem_intersecao_nunca_e_relevante():
    assert not relevante(_p(0, 1200), (2000, 2200))
