"""Testes do crivo da Fase 0.

Dois alvos distintos, de propósito:

1. a LÓGICA dos critérios (roda sempre, no CI, sem o corpus) — um critério que não reprova nada
   é decoração, então cada um é exercitado contra uma medida que ele DEVE reprovar;
2. o ARTEFATO medido (só roda onde o corpus existe) — trava os números publicados.

O nº 1 existe porque o crivo da Fase 0 do RodoQuery quase publicou uma subcontagem de 61% dos
PDFs: `rglob("*.pdf")` é case-sensitive e 311 arquivos vêm com `.PDF`. Critério só vale se
alguém já o viu dizer não.
"""
import json
from pathlib import Path

import pytest

from fase0_dados import CRITERIOS

ARTEFATO = Path(__file__).resolve().parents[1] / "reports" / "fase0" / "aptidao_cuad.json"
precisa_artefato = pytest.mark.skipif(
    not ARTEFATO.exists(), reason="corpus CUAD não perfilado nesta máquina"
)

# Medida que passa em TODOS os critérios — a base dos controles negativos abaixo.
BOA = {
    "n_contratos": 510, "n_perguntas": 20_910, "taxa_is_impossible": 0.68,
    "taxa_span_confere": 1.0, "gold_humano": True, "licenca_ok": True, "chars_mediana": 33_425,
}

# Para cada critério, um campo estragado que DEVE derrubá-lo.
QUEBRA = {
    "1_volume_contratos":   ("n_contratos", 299),
    "2_volume_perguntas":   ("n_perguntas", 4_999),
    "3_recusa_e_maioria":   ("taxa_is_impossible", 0.49),
    "4_gold_verificavel":   ("taxa_span_confere", 0.98),
    "5_gold_humano":        ("gold_humano", False),
    "6_licenca_permissiva": ("licenca_ok", False),
    "7_texto_substancial":  ("chars_mediana", 9_999),
}


def test_todos_os_criterios_tem_controle_negativo():
    """Se um critério novo entrar sem controle negativo, este teste falha — de propósito."""
    assert set(CRITERIOS) == set(QUEBRA)


@pytest.mark.parametrize("chave", sorted(CRITERIOS))
def test_criterio_aprova_a_medida_boa(chave):
    assert CRITERIOS[chave][1](BOA) is True


@pytest.mark.parametrize("chave", sorted(QUEBRA))
def test_criterio_reprova_quando_deve(chave):
    campo, ruim = QUEBRA[chave]
    assert CRITERIOS[chave][1]({**BOA, campo: ruim}) is False, \
        f"{chave} não reprovou {campo}={ruim}"


@precisa_artefato
def test_artefato_medido_bate_com_o_publicado():
    m = json.loads(ARTEFATO.read_text(encoding="utf-8"))
    assert m["veredito"] == "GO"
    med = m["medidas"]
    assert med["n_contratos"] == 510
    assert med["n_contratos_distintos"] == 510
    assert med["n_pdf"] == 510, "contagem de PDF é case-insensitive (311 arquivos são .PDF)"
    assert med["n_perguntas"] == 20_910
    assert med["n_impossiveis"] == 14_208
    assert med["taxa_is_impossible"] == 0.6795
    assert med["n_categorias"] == 41
    # O gold ser verificável NO OFFSET é o que permite avaliação sem juiz-LLM.
    assert med["taxa_span_confere"] == 1.0


@precisa_artefato
def test_as_partes_somam_o_total():
    med = json.loads(ARTEFATO.read_text(encoding="utf-8"))["medidas"]
    assert med["n_impossiveis"] + med["n_respondiveis"] == med["n_perguntas"]
