# NãoConsta

**Um agente de RAG contratual avaliado pelo que ele se recusa a responder.**

[![CI](https://github.com/alanjoffre/naoconsta/actions/workflows/ci.yml/badge.svg)](https://github.com/alanjoffre/naoconsta/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Fase](https://img.shields.io/badge/fases-0–1-e0a326.svg)
![Recall](https://img.shields.io/badge/recall%4010-78%2C8%25%20·%20portão%20em%2085%25%20FECHADO-c0392b.svg)
![Corpus](https://img.shields.io/badge/CUAD-510%20contratos%20·%2020.910%20perguntas-blue.svg)
![Sem resposta](https://img.shields.io/badge/sem%20resposta-68%2C0%25-c0392b.svg)

Quase todo demo de RAG mede **acerto**. Este mede **recusa** — porque num corpus jurídico real a
maioria das perguntas não tem resposta no documento, e um agente que sempre responde é um agente
que alucina 68% das vezes com confiança.

> **A tese, falsificável:** num corpus onde a maioria das perguntas não tem resposta, o eixo que
> discrimina um agente de RAG é a **abstenção**, não a acurácia.

É o achado central do [RodoQuery](https://github.com/alanjoffre/rodoquery) — onde a acurácia
saturou em 100% e só a abstenção seguiu discriminando — levado para **outro domínio** e **outra
stack**, para ver se sobrevive fora de casa.

## Por que o CUAD sustenta essa medição

Números **medidos** por [`fase0_dados.py`](fase0_dados.py), não citados de terceiros
([artefato](reports/fase0/aptidao_cuad.json)):

| | |
|---|---|
| Contratos comerciais reais | **510** (PDF + TXT, títulos distintos) |
| Perguntas rotuladas | **20.910**, em 41 categorias de cláusula |
| **Sem resposta (`is_impossible`)** | **14.208 — 68,0%** |
| Spans de resposta | 13.823, **100% conferem** no offset declarado |
| Gold | **humano** — estudantes de direito treinados por advogados (eBrevia) |
| Licença | **CC BY 4.0**, uso comercial permitido |
| Texto | 26,8 M caracteres · mediana de 33.425 por contrato |

Dois detalhes fazem a diferença entre um benchmark e uma demo:

- **O gold é humano.** No RodoQuery ele saía de um compilador (MetricFlow), o que garantia
  consistência mas não julgamento. Aqui foram advogados em formação, com processo documentado.
- **Os spans conferem byte a byte no offset.** Isso permite avaliar **recuperação sem juiz-LLM** —
  sem que o próprio modelo seja parte da régua que o mede.

## Fase 0 de Dados: go/no-go antes de construir

Trocar de base no início custa um dia; descobrir no fim que a base não sustenta a tese custa o
projeto. Os sete critérios foram **declarados antes de olhar o dado** e estão no código:

```
PASSA  1_volume_contratos       ≥ 300 contratos com texto extraído
PASSA  2_volume_perguntas       ≥ 5.000 perguntas rotuladas
PASSA  3_recusa_e_maioria       ≥ 50% das perguntas SEM resposta   ← o eixo da tese
PASSA  4_gold_verificavel       ≥ 99% dos spans batem no offset declarado
PASSA  5_gold_humano            rótulo é humano, não de máquina
PASSA  6_licenca_permissiva     licença permite uso em portfólio público
PASSA  7_texto_substancial      mediana ≥ 10.000 caracteres por contrato

VEREDITO: GO
```

Cada critério tem um **controle negativo** nos testes — é exercitado contra uma medida que ele
*deve* reprovar. Critério que nunca disse não é decoração. Há inclusive um teste que falha se um
critério novo entrar sem controle negativo.

### Um defeito do próprio crivo, achado antes de publicar

`rglob("*.pdf")` é *case-sensitive*, e **311 dos 510** arquivos vêm com `.PDF` maiúsculo: o crivo
reportou **199 PDFs** e teria publicado uma subcontagem de 61%. Peguei conferindo o disco contra o
ZIP, extensão por extensão (1051 = 1051). Pelo mesmo motivo, licença e anotador saíam de regex
frouxa — o termo *"License Grant"*, que é um **tipo de cláusula do corpus**, casava com
`/licen[cs]e/` e imprimia um trecho sem relação com licenciamento.

Também comparei a **fonte oficial** (Zenodo/Atticus Project) com o espelho do Kaggle antes de
escolher: o espelho hoje devolve **403**, e espelho costuma ser subconjunto desatualizado.

## Rodar

```bash
git clone https://github.com/alanjoffre/naoconsta && cd naoconsta
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"          # o mesmo extra que o CI usa
bash baixar_cuad.sh               # corpus da fonte oficial, ~106 MB, fora do repo
python fase0_dados.py             # crivo de aptidão, com go/no-go
pytest -q                         # 17 testes
python verificar_coleta.py        # nenhum teste some por falta de extra
bash ensaiar_ci.sh --negativo     # ensaia o CI num clone limpo, com controle negativo
```

## Engenharia, desde o commit nº 1

O CI deste repositório **nasceu verde e é verificado antes de cada push**. Isso não é obviedade:
no RodoQuery o CI nasceu na Fase 5 e ficou **vermelho da Fase 6 até a 22 — 32 execuções, 12 dias** —
porque o runner instalava um extra a menos e ninguém leu o badge. As travas que saíram daquela
fase vieram junto para cá:

- **extra `[test]` nomeado** no `pyproject.toml`, em vez de lista mágica no YAML;
- **`pythonpath = ["."]`**, porque `pytest` (console script) e `python -m pytest` não enxergam o
  mesmo `sys.path` — uma letra de comando separava a máquina local do runner;
- **[`verificar_coleta.py`](verificar_coleta.py)** em *subprocesso*, invocando o mesmo executável
  que o CI usa: a primeira versão rodava in-process e deu **falso negativo** exatamente na classe
  de defeito que existe para pegar;
- **[`ensaiar_ci.sh`](ensaiar_ci.sh)** com **controle negativo**: quebra o `pythonpath` de
  propósito e exige que a trava reprove.

> **Verde com teste faltando é pior que vermelho** — vermelho ao menos grita.

## Próximas fases

| Fase | Pergunta | Estado |
|:---:|---|---|
| **0** · Dados | o corpus sustenta a tese da recusa? | ✅ **GO**, 7/7 critérios |
| **1** · Recuperação | pgvector acha o span certo? (`recall@k` contra offset humano, **sem juiz-LLM**) | ⚠️ **portão fechado em 78,8% < 85%** · o defeito estava na **pergunta**, não no modelo (+9,0 pp) · **o índice HNSW nunca foi usado** |
| **2** · Agente | grafo LangGraph com decisão explícita de **abstenção** | ⛔ **bloqueada pelo pré-registro** |
| **3** · Avaliação | acurácia **×** abstenção, com IC e teste pareado | ⏳ |
| **4** · MCP | expor a recuperação como servidor MCP | ⏳ |

## Fase 1 — o que a medição refutou

Detalhe em [`docs/FASE1_RECUPERACAO.md`](docs/FASE1_RECUPERACAO.md); a previsão está em
[`docs/FASE1_PREREGISTRO.md`](docs/FASE1_PREREGISTRO.md), **commitada antes de rodar**.

| sistema | recall@5 | recall@10 |
|---|---:|---:|
| `denso_bruto` *(config. pré-registrada)* | 56,3% | 69,8% |
| `denso_enxuto` | 65,3% | **78,8%** |
| `bm25` | 62,0% | 73,1% |
| `hibrido_rrf` | **67,4%** | 78,6% |
| `primeiros` *(espantalho posicional)* | 35,7% | 46,2% |
| `aleatorio` *(piso da sorte)* | 21,3% | 38,0% |

- **O defeito estava na PERGUNTA, não no modelo.** As 41 perguntas do CUAD abrem com o mesmo
  preâmbulo (*"Highlight the parts (if any)… reviewed by a lawyer"*), e isso deixava o cosseno
  médio entre perguntas **diferentes** em **0,735** — 41 consultas quase colineares. Apagando o
  preâmbulo: 0,594, e **+9,0 pp** de recall (McNemar p = 2×10⁻¹⁰⁰). O BM25 nunca sofreu disso, e
  era só por isso que parecia melhor. *Falha mecânica se conserta em código — aqui, apagando prosa.*
- **O índice HNSW nunca foi usado.** Montei um sistema para medir a armadilha do filtro por
  metadado; ele deu idêntico ao exato nos 4 valores de k porque o `EXPLAIN` revela `top-N
  heapsort` — com `WHERE contrato = ?` pegando 0,2% das linhas, o planner ignora o HNSW. Retirei a
  comparação. **Para busca dentro de um documento, o índice vetorial é peso morto.**
- **Minha hipótese do prefixo estava errada.** `search_query:`/`search_document:` do
  `nomic-embed-text`: 56,2% sem × 55,2% com. Medi em vez de supor, e a suposição caiu.
- **O portão fechou.** Pré-registrei recall@10 ≥ 85%; o melhor é 78,8%. A margem sobre o BM25
  ficou positiva (+5,7 pp, p = 5×10⁻²⁴), mas o limiar não. **A Fase 2 não começa** — construir
  agente sobre recuperação fraca é medir o agente contra o próprio ruído.

## Licença

Código sob MIT. O corpus **CUAD** é do [Atticus Project](https://www.atticusprojectai.org/cuad),
sob **CC BY 4.0**, e **não** está versionado aqui — `baixar_cuad.sh` o traz da fonte oficial.
