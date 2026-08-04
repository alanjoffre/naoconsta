# Fase 1 — pré-registro da recuperação

Escrito e **commitado antes de rodar a avaliação**. Serve para que o resultado possa me
contrariar: previsão feita depois de ver o número não é previsão, é narrativa.

No RodoQuery isso já me pegou uma vez — na Fase 19 registrei −9 pp e medi 0,00 pp. A afirmação
falsificável central sobreviveu; a previsão pontual, não. É o comportamento esperado de um
pré-registro que vale alguma coisa.

## O que está sendo medido

**Recall@k por consulta**, contra o offset humano do CUAD. Uma consulta conta como acerto se
**algum** dos k chunks devolvidos é relevante para **algum** span do gold, com relevância definida
em `corpus.py` (interseção ≥ 50% do span **ou** ≥ 50% do chunk — a regra é simétrica para cobrir
tanto o span curto quanto o span que não cabe no chunk).

**Não há juiz-LLM em nenhuma parte desta fase.** O gold é offset de caractere anotado por humano;
a régua é aritmética de intervalos. É a única fase do projeto em que isso será verdade de graça, e
por isso ela é a fundação: se a recuperação for ruim, nenhum número das fases seguintes significa
o que aparenta.

**Escopo:** busca filtrada por contrato. As 41 perguntas do CUAD se repetem em todos os 510
contratos (medido: 41 textos distintos, o mais repetido 510×), então busca no corpus inteiro é
pergunta mal-posta. O índice guarda os ~26 mil chunks juntos e a consulta filtra — padrão
multi-tenant, não atalho.

**Universo:** apenas as **6.702 consultas respondíveis**. As 14.208 sem resposta não têm span e
portanto não têm recall; elas são o objeto das Fases 2–3, não desta.

## Sistemas comparados

| | o que é |
|---|---|
| `denso` | pgvector + `nomic-embed-text` (768d, cosseno, HNSW) |
| `bm25` | BM25 escrito à mão (k1=1,5, b=0,75), mesmo escopo por contrato |
| `primeiros` | devolve sempre os k **primeiros** chunks — espantalho posicional |
| `aleatorio` | k chunks sorteados — o piso da sorte |

## As previsões, com números

1. **`denso` > `bm25` no recall@5 global**, mas por **menos de 15 pp**. Contrato é texto com
   termos raros e literais (*escrow*, *most favored nation*), o regime em que o lexical é forte.
2. **`bm25` vence `denso` em pelo menos 5 das 41 categorias** — justamente as de vocabulário
   cirúrgico. Se o denso vencer em todas as 41, desconfio de vazamento antes de comemorar.
3. **`primeiros` faz recall@5 ≥ 25%.** A dispersão mediana dos spans é 0,04 e há categorias
   (`Document Name`, `Parties`, `Agreement Date`) que vivem no cabeçalho do contrato. Se esse
   espantalho ficar perto do sistema, o mérito da recuperação é menor do que o número global sugere.
4. **`aleatorio` ≤ 20% no recall@5** (contrato mediano ~28 chunks, k=5).
5. **Recall@10 do `denso` ≥ 85%.** Abaixo disso a recuperação vira o gargalo do projeto e a
   Fase 2 tem de esperar.

## A afirmação falsificável central

> **A recuperação densa filtrada por contrato basta como fundação: recall@10 ≥ 85%, e a margem
> sobre o melhor baseline não trivial (`bm25`) é positiva.**

Se cair, a Fase 2 não começa — construir um agente sobre recuperação ruim é medir o agente
contra o próprio ruído.

## O que já sei que esta fase NÃO responde

- **Não diz nada sobre alucinação.** Recall mede se o texto certo foi encontrado, não se o
  modelo o usa nem se ele inventa quando não há nada. Esse é o eixo da tese, e ele começa na Fase 2.
- **41 consultas distintas não são 41 consultas independentes** repetidas 510 vezes em contratos
  diferentes; os itens são pareados por pergunta, e qualquer teste estatístico terá de respeitar
  isso.
- **O chunker é ingênuo de propósito** (janela deslizante em caracteres). Um chunker por cláusula
  provavelmente ajudaria — e seria uma variável a mais entre o dado e o resultado nesta fase.
