# Fase 1b/1c — três alavancas medidas, e o meu portão era manipulável

A [Fase 1](FASE1_RECUPERACAO.md) fechou o portão em **78,8% < 85%**. Antes de decidir o que fazer,
medi as alavancas óbvias. Duas morreram, e a terceira revelou um defeito no critério que eu mesmo
tinha pré-registrado.

Tudo aqui roda numa **amostra de 60 contratos** (799 consultas respondíveis, semente 20260803),
porque reindexar 26.952 chunks a cada hipótese custaria 25 min de GPU por tentativa. **A amostra é
mais fácil que o conjunto completo** — o `nomic` faz 81,5%@10 nela contra 78,8% no todo — então
ela serve para **comparar configurações**, nunca para declarar o portão aberto.

## Alavanca 1: modelo de embedding maior — REFUTADA, e ele é pior

| modelo | dims | vazão | recall@1 | recall@5 | recall@10 |
|---|---:|---:|---:|---:|---:|
| `nomic-embed-text` | 768 | 87,5 ch/s | 32,4% | **68,0%** | **81,5%** |
| `bge-m3` | 1024 | 34,3 ch/s | **34,4%** | 62,7% | 76,1% |

McNemar pareado, mesma amostra e mesmo gold: **−5,3 pp em @5 (p = 0,0018)** e **−5,4 pp em @10
(p = 1,2×10⁻⁴)**, com **2,5× menos vazão**. O ganho em @1 não é significativo (p = 0,24).

Um modelo multilíngue de 1024 dimensões perde para um de 768 em contrato jurídico em inglês, e
cobra 2,5× mais caro. É o achado da Fase 15 do RodoQuery noutro domínio: **"maior" não é a
variável; adequação é.**

## Alavanca 2: prefixo de tarefa — REFUTADA

O `nomic-embed-text` documenta os prefixos `search_query:` / `search_document:`. Em 400 consultas
pareadas: **56,2% sem × 55,2% com**. Não melhora; piora de leve. Hipótese minha, medida e
descartada.

## Alavanca 3: tamanho do chunk — e aqui está a armadilha

A varredura ingênua, com **k fixo**, diz que chunk maior é melhor:

| chunk/sobrep | chunks/contrato | recall@10 | caracteres varridos em @10 |
|---|---:|---:|---:|
| 800/150 | 72,4 | 77,2% | 8.000 |
| 1200/200 | 47,2 | 81,5% | 12.000 |
| 2000/300 | 27,9 | 86,9% | 20.000 |
| 3000/400 | 18,4 | **87,7%** | **30.000** |

O contrato mediano tem **33.425 caracteres**. Com chunks de 3.000, o `recall@10` varre 30.000 —
**~90% do contrato inteiro**. A essa altura a métrica não mede recuperação, mede *"devolvi quase
tudo"*.

Repetindo com **orçamento de texto fixo** — cada configuração recebe o k que cabe no mesmo número
de caracteres — a ordem **se inverte, monotonicamente**:

| chunk | 6.000 chars | 12.000 chars | 24.000 chars |
|---|---:|---:|---:|
| 300/60 | **81,6%** (k=20) | **90,7%** (k=40) | **95,5%** (k=80) |
| 400/75 | 80,2% (k=15) | 88,7% (k=30) | 94,9% (k=60) |
| 600/100 | 76,6% (k=10) | 87,4% (k=20) | 94,0% (k=40) |
| 800/150 | 71,6% (k=7) | 83,6% (k=15) | 92,6% (k=30) |
| 1200/200 *(atual)* | 68,0% (k=5) | 81,5% (k=10) | 90,9% (k=20) |
| 2000/300 | 58,8% (k=3) | 76,7% (k=6) | 89,4% (k=12) |
| 3000/400 | 51,7% (k=2) | 70,7% (k=4) | 85,4% (k=8) |

**Quanto menor o chunk, melhor** — monotonicamente, em todos os orçamentos, até o limite testado.
Os 87,7% do chunk de 3.000 eram contabilidade: ele varria 2,5× mais texto que o de 1.200. E o
ganho não é pequeno: a 12.000 caracteres, trocar 1.200 por 300 vale **+9,2 pp sem gastar um
caractere a mais**.

Não há joelho na curva. O span mediano tem 196 caracteres, então chunks de 300 já estão na escala
da própria resposta — abaixo disso a regra de relevância (≥50% do span) começaria a trabalhar
contra, mas isso não foi medido e fica declarado como não testado.

## O defeito que isso expõe no meu pré-registro

> **O portão `recall@10 ≥ 85%` é manipulável por tamanho de chunk.**

O chunk de 3.000 **atravessa o portão** com 87,7% sendo **pior recuperação em qualquer orçamento
justo**. Se eu tivesse rodado só a varredura ingênua, teria aberto o portão **piorando o sistema**,
e com um número pré-registrado para legitimar.

A causa é que `k` conta **pedaços**, não **evidência**. Dois sistemas com o mesmo k entregam
quantidades de texto diferentes ao agente, e é o texto que custa contexto, dinheiro e — o que mais
importa aqui — **capacidade de abstenção**.

**Retiro o portão como estava** e o re-especifico em orçamento de texto:

> **Portão v2: `recall` com 12.000 caracteres de orçamento ≥ 85%**, medido no conjunto completo.

12.000 é o orçamento que a configuração atual (1.200 × k=10) já gasta, então a régua nova não
afrouxa nada: ela apenas deixa de premiar quem varre mais.

## Por que chunk grande é pior justamente para ESTE projeto

A tese é sobre **recusa**. Entregar 30.000 caracteres — 90% do contrato — ao agente é o cenário em
que ele *sempre* acha algo parecido com uma resposta. Chunk grande compra recall e **paga em
abstenção**, que é exatamente o eixo que o projeto existe para medir.

É a troca da Fase 21 do RodoQuery noutro traje: **catálogo maior comprou cobertura e pagou em
ambiguidade**; aqui, chunk maior compra recall e paga em alucinação. Otimizar a métrica errada
teria custado a tese.

## O custo escondido do chunk pequeno

A curva não é de graça, e o preço não aparece no recall:

- **Fragmentação.** A 12.000 caracteres, 300/60 entrega **40 fragmentos** de ~50 palavras contra
  10 pedaços de ~200. O texto total é o mesmo; a legibilidade, não. Se o agente da Fase 2 lê pior
  40 cacos do que 10 trechos, o ganho de recall vira prejuízo — e isso **não** foi medido aqui.
- **Custo de índice.** 300/60 dá ~196 chunks por contrato: no corpus completo são ~100 mil vetores
  contra 26.952, com o tempo de indexação e o tamanho da tabela subindo na mesma proporção.

Por isso a validação no conjunto completo testa **400/75** junto com 300/60: se os dois passarem o
portão, o 400 é preferível por entregar 30 fragmentos em vez de 40, com índice 27% menor.

## Onde isso deixa a decisão

Na amostra, **três configurações passam o portão v2** (≥85% em 12.000 caracteres): 300/60 com
90,7%, 400/75 com 88,7% e 600/100 com 87,4%. Mas amostra não abre portão — a de 60 contratos é
~2,7 pp mais fácil que o conjunto completo, e 87,4% menos 2,7 já cai abaixo de 85%.

A validação no conjunto completo (`fase1d_validar.py`, 510 contratos, 6.702 consultas) é o que
decide, e o resultado dela está em [`FASE1_RECUPERACAO.md`](FASE1_RECUPERACAO.md).
