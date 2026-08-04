# Fase 1 — a recuperação, e três coisas que me contrariaram

Recall@k contra o offset humano do CUAD, em **6.702 consultas respondíveis**, 510 contratos,
26.952 chunks. **Sem juiz-LLM em nenhuma parte**: o gold é offset de caractere anotado por
advogados em formação e a régua é aritmética de intervalos.

## O resultado

| sistema | recall@1 | recall@3 | recall@5 | recall@10 |
|---|---:|---:|---:|---:|
| `denso_bruto` *(a configuração pré-registrada)* | 28,3% | 46,9% | 56,3% | 69,8% |
| `denso_enxuto` | 33,3% | 54,7% | **65,3%** | **78,8%** |
| `bm25` | 33,8% | 53,3% | 62,0% | 73,1% |
| `hibrido_rrf` | **39,3%** | **58,5%** | **67,4%** | 78,6% |
| `primeiros` *(espantalho posicional)* | 24,4% | 30,9% | 35,7% | 46,2% |
| `aleatorio` *(piso da sorte)* | 5,1% | 13,8% | 21,3% | 38,0% |

## O veredito do pré-registro: metade confirmada, metade refutada

A [afirmação falsificável central](FASE1_PREREGISTRO.md) tinha duas metades, e elas não caíram
juntas:

- **margem positiva sobre o BM25 — CONFIRMADA.** `denso_enxuto` × `bm25`: +5,7 pp em @10,
  McNemar 906 × 525, **p = 5,2×10⁻²⁴**.
- **recall@10 ≥ 85% — REFUTADA.** O melhor sistema faz **78,8%**. Faltam 6,2 pp.

Das cinco previsões numéricas, **três caíram**: `denso > bm25` (falso na configuração
pré-registrada, verdadeiro só depois do conserto), `aleatorio ≤ 20%` (deu 21,3%) e o próprio
teto de 85%. A que eu mais errei foi a previsão 2 — apostei que o BM25 venceria em "pelo menos 5
das 41 categorias"; ele vence em **19**, e vencia em 26 antes do conserto.

**A regra que eu mesmo escrevi diz que a Fase 2 não começa.** Ela está valendo: o agente não é
construído sobre 78,8%. O que muda é *o que fazer a seguir*, e isso está no fim deste documento.

## O que me contrariou (1): o índice HNSW nunca foi usado

Eu havia montado um sistema `denso_hnsw` para medir a armadilha clássica do banco vetorial — o
filtro por metadado aplicado **depois** da busca aproximada, que faz o índice devolver menos que
k. Ele deu resultado **idêntico ao exato, dígito a dígito, nos quatro valores de k**.

Não era coincidência. O `EXPLAIN ANALYZE` mostra, com e sem `enable_indexscan`:

```
Limit → Sort → Sort Method: top-N heapsort  Memory: 25kB
```

Nenhuma menção a `pedaco_vetor`. Com `WHERE contrato = ?` selecionando **53 de 26.952 linhas
(0,2%)**, o planner ignora o HNSW e ordena exato — que é a decisão **certa**. Eu não testei a
armadilha; testei a mesma coisa duas vezes com nomes diferentes, e **retiro a comparação**.

O achado de engenharia que sobra é melhor que o que eu procurava:

> Para recuperação **dentro de um documento**, o índice vetorial é peso morto. Construí um HNSW
> (12,9 s, parte dos 248 MB de tabela+índices) que o banco nunca usa. Um contrato tem ~53 chunks;
> varrer 53 vetores é mais barato que consultar um grafo aproximado de 26.952.

Por isso a avaliação final calcula a similaridade em numpy: como o Postgres já fazia cálculo
**exato**, o resultado é idêntico e permite rodar os seis sistemas sobre os mesmos vetores. O que
se perde é a ilusão de estar exercitando ANN — e é essa ilusão que esta fase documenta.

## O que me contrariou (2): a hipótese do prefixo era minha, e estava errada

O `nomic-embed-text` exige prefixos de tarefa (`search_query:` / `search_document:`) e eu não os
usara. Hipótese forte, mecânica, do tipo que já explicou defeito antes. **Medida em 400 consultas
pareadas: 56,2% sem prefixo × 55,2% com.** Não melhora; piora de leve. Descartada.

Vale registrar que a amostra de 400 deu 56,2% contra 56,3% do conjunto inteiro — a amostragem
estava sã, então o resultado negativo é do prefixo, não do teste.

## O que me contrariou (3) — e este consertou tudo: o defeito estava na PERGUNTA

As 41 perguntas do CUAD abrem com o mesmo preâmbulo:

> *"Highlight the parts (if any) of this contract related to **"X"** that should be reviewed by a
> lawyer. Details: …"*

Esse texto é idêntico em todas. **Medido:** o cosseno médio entre perguntas **diferentes** é
**0,735** (máximo 0,944). Ou seja, o embedding via 41 consultas quase colineares — o preâmbulo
dominava o vetor e o discriminante virava ruído de fundo. Tirando o preâmbulo, o cosseno médio cai
para **0,594**.

O efeito no recall é o maior desta fase:

| | recall@5 | recall@10 |
|---|---:|---:|
| `denso_bruto` | 56,3% | 69,8% |
| `denso_enxuto` | **65,3%** | **78,8%** |
| McNemar (@5) | 743 × 139 | **p = 2,1×10⁻¹⁰⁰** |

**+9,0 pp nos dois k**, e isso inverte a conclusão: antes o BM25 vencia o denso por 5,7 pp; depois
o denso vence por 3,3 pp em @5 e 5,7 pp em @10.

E o BM25 nunca sofreu do problema — ele pontua termo a termo, e um preâmbulo presente em todas as
consultas não muda o ranking **dentro** de um contrato. **A busca lexical era robusta a um defeito
que destruía a densa**, e é por isso que ela parecia melhor.

> É a lei do [RodoQuery](https://github.com/alanjoffre/rodoquery) outra vez, e desta vez ao pé da
> letra: **falha mecânica se conserta em código, não em prosa** — aqui, o conserto *foi apagar
> prosa*. Nenhuma linha do modelo, do índice ou do chunker mudou.

## O híbrido ajuda, mas só onde o k é curto

`hibrido_rrf` (fusão RRF, k=60, de `denso_enxuto` + `bm25`) é o melhor em @1, @3 e @5 — em @5 vence
o denso por 2,1 pp, McNemar 567 × 426, **p = 8,6×10⁻⁶**. Em **@10 empata**: 78,6% × 78,8%,
408 × 422, **p = 0,65**.

Leitura honesta: o híbrido **reordena melhor o topo**, não encontra mais documentos. Se a Fase 2
for entregar 10 chunks ao agente, ele não paga o próprio custo; se entregar 3, paga.

## O que os baselines triviais dizem sobre o mérito

`primeiros` faz **35,7%@5** sem nenhuma inteligência — porque `Document Name`, `Parties` e
`Agreement Date` moram no cabeçalho do contrato, e a dispersão mediana dos spans é 0,04. E
`aleatorio` faz **21,3%@5** porque o contrato mediano tem ~28 chunks e k=5 é uma fração grande dele.

Então dos 67,4% do híbrido, **21,3 pp são sorte** e mais uma fatia é posição. O número que mede
recuperação de verdade é a margem sobre esses pisos, não o valor absoluto — e é por isso que
publicar "67% de recall@5" sem baseline seria propaganda.

## Limitações declaradas

- **41 consultas distintas, repetidas até 510×.** Os 6.702 itens não são independentes; qualquer
  leitura por categoria tem n efetivo muito menor que o global.
- **O chunker é ingênuo de propósito** (janela de 1.200/200 em caracteres). **0 consultas ficaram
  sem chunk relevante**, então o fatiamento não é o teto — mas um chunker por cláusula
  provavelmente subiria o número, e seria uma variável a mais nesta fase.
- **O `enxugar` é pós-hoc.** Foi escrito *depois* de ver o resultado ruim, então o ganho de 9 pp
  está honestamente rotulado como conserto de defeito, não como previsão confirmada. O
  pré-registro segue no repositório com a previsão que fiz, não com a que eu gostaria de ter feito.
- **Um só modelo de embedding.** `nomic-embed-text` (768d). Trocar por um modelo maior é a
  próxima alavanca óbvia e ainda não foi medida.

## O que decide a Fase 2

O portão está fechado em **78,8% < 85%**. Três caminhos, e todos são medíveis antes de codar agente:

1. **Modelo de embedding maior** (`bge-m3`, 1024d) — a alavanca não testada, ~15 min de
   reindexação, custo zero.
2. **Chunker por cláusula** em vez de janela cega — provável ganho, e o CUAD tem a estrutura.
3. **Baixar o portão para 78,8% e declarar o teto** — legítimo *se* declarado, porque um agente
   com recall@10 de 78,8% ainda pode ser avaliado, desde que o teto entre em toda leitura da
   Fase 3.

O que **não** é opção é seguir para o LangGraph fingindo que o portão passou.
