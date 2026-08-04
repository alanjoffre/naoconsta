# Fase 2 — pré-registro do agente

Commitado **antes de rodar**. Na Fase 1 o pré-registro me pegou duas vezes: derrubou três das
cinco previsões e, melhor ainda, revelou que o meu próprio portão era manipulável. Não é ritual.

## O que o agente faz

Grafo **LangGraph** com três nós, e o terceiro é o que interessa:

```
recuperar ──▶ decidir ──▶ verificar ──▶ (responde | não consta)
 k=30 × 400   LLM emite    guarda
 = 12k chars  JSON         DETERMINÍSTICA
```

1. **`recuperar`** — 30 chunks de 400 caracteres do contrato (orçamento de 12.000, o da Fase 1,
   recall medido de **88,1%**).
2. **`decidir`** — o LLM recebe pergunta + trechos numerados e devolve
   `{"decisao": "responde"|"nao_consta", "trecho": <id|null>, "citacao": "<literal>"}`.
3. **`verificar`** — se o agente diz que responde, a **citação tem de aparecer literalmente** em
   um dos trechos recuperados. Se não aparecer, é alucinação, e o grafo **força a abstenção**.

O nó 3 é o coração do projeto: ele transforma *"confie no modelo"* em *"verifique estruturalmente"*,
sem juiz-LLM. É a mesma ideia do RodoQuery, onde o vocabulário fechado era imposto pelo
**compilador** e não pedido no prompt — só que aqui o que se impõe é a **procedência do texto**.

## Como isso é avaliado sem juiz-LLM

Três checagens, todas aritméticas:

| pergunta | como se decide |
|---|---|
| a citação é real? | `citacao in chunk_recuperado` — comparação de string |
| a citação é a resposta certa? | o intervalo da citação no contrato **intersecta o span do gold** |
| absteve quando devia? | `is_impossible` do CUAD, rótulo humano |

Nenhum modelo participa da régua em nenhum dos três.

## Os dois sistemas comparados

| | |
|---|---|
| `agente_com_guarda` | o grafo completo, com o nó `verificar` |
| `agente_sem_guarda` | idêntico, com o nó `verificar` desligado |

A diferença entre eles **é** o valor da camada determinística. O RodoQuery mediu essa mesma
grandeza três vezes e formulou a lei: *a ajuda de uma muleta é inversamente proporcional à força
do SUT* (normalizadores +17,7 pp num 7B → 0,0 pp num modelo de fronteira).

**SUT desta fase: `qwen2.5:7b` local, custo zero.** Um 7B é justamente o regime em que a lei prevê
que a guarda vale muito.

## As previsões, com números

1. **A guarda pega ≥ 10% das respostas do `agente_sem_guarda`** como citação inexistente no
   contexto. Abaixo disso, a guarda é decoração num 7B.
2. **`agente_com_guarda` tem acurácia de abstenção ≥ 15 pp maior** que o `sem_guarda`. A guarda só
   converte resposta em abstenção, então ela **não pode** melhorar o lado respondível — e é isso
   que torna a previsão falsificável em vez de vaga.
3. **O `sem_guarda` abstém em < 40% das `is_impossible`.** Um 7B com 12.000 caracteres na frente
   quase sempre acha algo que parece resposta — é a hipótese central do projeto, e se ela falhar
   aqui, a tese perde o seu caso mais forte.
4. **Acurácia nas respondíveis ≤ 55%.** O teto de recuperação é 88,1%, e o modelo ainda precisa
   escolher o trecho certo entre 30.
5. **≥ 5% das saídas do LLM virão com JSON malformado** e serão tratadas como falha explícita,
   não silenciosa.

## A afirmação falsificável central

> **A guarda determinística de procedência muda a abstenção materialmente (≥ 15 pp) sem tocar no
> prompt nem no modelo.**

Se cair, o nó `verificar` não se justifica e o grafo deve ser simplificado.

## O teto que entra em toda leitura

**11,9% das consultas respondíveis não têm o span no material entregue** (recall de 88,1%). Nesses
casos, abster é o comportamento **certo pelo motivo errado** — o agente não tinha como responder.
A Fase 3 precisa separar *"absteve porque julgou ausente"* de *"absteve porque de fato não estava
lá"*, e qualquer taxa de abstenção reportada sem essa separação é enganosa.

## O que esta fase NÃO responde

- **Não compara com um SUT de fronteira.** Isso custa dinheiro e exige aprovação do Alan; a
  estimativa vai medida antes de qualquer chamada paga.
- **Não mede latência de produção.** O grafo roda em lote, não sob SLO.
- **Não testa MCP.** É a Fase 4.
