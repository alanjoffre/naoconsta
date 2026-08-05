# Fase 2 — o agente, e o modo de falha que eu previ ao contrário

Grafo LangGraph de três nós sobre a recuperação da Fase 1. **200 consultas estratificadas**
(100 respondíveis, 100 sem resposta), SUT `qwen2.5:7b` local, k=30 × 400 caracteres — o orçamento
de 12.000 medido na Fase 1. Custo: **zero**.

```
recuperar ──▶ decidir ──▶ verificar ──▶ (responde | não consta)
 k=30 × 400   LLM emite    guarda
 = 12k chars  JSON         DETERMINÍSTICA
```

O nó `verificar` exige que a citação apareça **literalmente** no material recuperado. Se não
aparecer, o texto não veio do contrato — veio do modelo — e o grafo força a abstenção. É a ideia
central do [RodoQuery](https://github.com/alanjoffre/rodoquery) noutra forma: lá o vocabulário
fechado não era *pedido* no prompt, era **imposto pelo compilador**. Aqui o que se impõe é a
**procedência do texto**, e a checagem é comparação de string.

**Isso mantém a avaliação sem juiz-LLM.** As três perguntas são aritméticas: a citação existe no
material? o intervalo dela intersecta o span do gold? o CUAD marcou como `is_impossible`? Nenhum
modelo participa da régua que o mede.

## O resultado

| | sem guarda | com guarda |
|---|---:|---:|
| respondíveis | 33/100 = 33,0% | 33/100 = 33,0% |
| respondíveis **com a evidência entregue** | 32/87 = 36,8% | 32/87 = 36,8% |
| abstenção | 90/100 = 90,0% | **91/100 = 91,0%** |
| **total** | 123/200 = 61,5% | **124/200 = 62,0%** |

Teto de recuperação: **87 de 100** respondíveis tinham a evidência no material entregue.
JSON malformado: **2 de 200 (1,0%)**.

## O pré-registro caiu em 3 das 5 previsões

| previsão, [commitada antes de rodar](FASE2_PREREGISTRO.md) | medido | |
|---|---|---|
| 1. a guarda pega ≥10% das respostas | **11,6%** (8 de 69) | ✅ |
| **2. delta de abstenção ≥ 15 pp** | **+1,0 pp** (McNemar 1×0, p=1) | ❌ |
| 3. sem guarda, abstém em < 40% | **90,0%** | ❌ |
| 4. acurácia nas respondíveis ≤ 55% | 33,0% | ✅ |
| 5. ≥5% de JSON malformado | 1,0% | ❌ |

**A afirmação falsificável central está refutada.**

## O modo de falha é o oposto do que eu previ

A previsão nº 3 é a que errei por mais — 50 pontos. Apostei que um 7B com 12.000 caracteres na
frente *sempre acharia algo parecido com resposta*: essa era a hipótese que motivou a guarda, e é
a intuição que a tese do projeto carrega.

Ele abstém em **90%** das perguntas sem resposta. O problema dele **não é alucinar — é não
responder**: acerta **33%** das respondíveis mesmo com a evidência entregue em 87 de 100 casos.
Ele deixa dois terços das respostas na mesa.

> A tese diz que *num corpus onde a maioria das perguntas não tem resposta, o eixo que discrimina
> é a recusa*. Com um SUT fraco a recusa está **fácil** (90%), e quem discrimina é a **resposta**.
> Isso não refuta a tese — mostra que **ela depende da força do modelo**, exatamente como a lei da
> Fase 18 do RodoQuery previa para muletas: *a ajuda de uma muleta é inversamente proporcional à
> força do SUT*.

Testar isso exige um SUT capaz de responder. É a Fase 2b, e está declarada como aberta.

## A guarda tinha um defeito meu, e o piloto o expôs

Na primeira execução a guarda **piorou** o placar: 123 → **121**. Ela barrou 13 respostas.
Investigando as 13:

| categoria | n | veredito |
|---|---:|---|
| citação **não existe** no contrato | 7 | guarda **certa** — alucinação real |
| citação atravessa **trechos adjacentes** | 4 | guarda **errada** |
| citação fora do material entregue | 2 | guarda certa |

E os **3 acertos perdidos eram todos do grupo do meio**, com citações de **376, 438 e 541**
caracteres — todas maiores que o chunk de 400. Uma citação de 541 caracteres **não cabe** num
trecho de 400: a guarda a reprovava **por construção**, mesmo sendo texto legítimo que o agente viu.

**A causa é acoplamento entre fases.** A Fase 1d trocou o chunk de 1.200 para 400 por um motivo
bom e medido, sem relação nenhuma com a guarda — e isso quebrou **em silêncio** um componente
escrito quando o chunk era três vezes maior.

A pergunta certa nunca foi *"cabe num pedaço?"* e sim **"veio do material que o agente viu?"**.
Trechos vizinhos formam texto contínuo do contrato. Corrigido com `blocos_contiguos`, que funde
trechos adjacentes sem duplicar a sobreposição:

| | v1 (defeituosa) | v2 (corrigida) |
|---|---:|---:|
| barrados | 13 | **8** |
| acertos perdidos | **3** | **0** |
| total | 123 → **121** | 123 → **124** |

Quatro testes novos cobrem o conserto, incluindo o que impede que ele vire frouxidão: trechos
**distantes** no contrato seguem **não** fundidos, senão passaria citação costurada de partes que o
agente viu mas que não são vizinhas.

## A leitura honesta da guarda

Ela é **neutra no placar e positiva na confiança**. Converte 8 respostas com citação fabricada em
abstenções — mas como só 1 delas caía numa pergunta sem resposta, o número quase não se move.

Melhorar o **comportamento** mostrado a um usuário sem melhorar a **pontuação** é diferente de ser
inútil, e é assim que está reportado. Com este SUT, porém, ela não paga a complexidade que
adiciona; o pré-registro dizia que nesse caso o nó deveria ser simplificado, e essa decisão fica
suspensa até a Fase 2b medir um SUT que de fato responda.

## O teto que entra em toda leitura

**13% das consultas respondíveis não tinham o span no material entregue** (87/100 nesta amostra;
88,1% no conjunto completo da Fase 1). Nesses casos, abster é o comportamento **certo pelo motivo
errado** — o agente não tinha como responder.

Por isso toda taxa aqui aparece em dois recortes: sobre **tudo** e sobre o subconjunto
**recuperável**. Só o segundo mede o agente; o primeiro mede o sistema. Uma taxa de abstenção
reportada sem essa separação seria enganosa.

## Um gasto que eu perdi

A primeira tentativa de rodar um SUT mais forte (`llama-3.3-70b` no Groq) **queimou ~98 mil tokens
da cota diária e não salvou nada**. Eu li `x-ratelimit-limit-tokens: 12000` e concluí que a
restrição era por **minuto**; existe também um teto por **dia** de 100.000, que só aparece quando
se estoura. 200 × ~2.795 = 559 mil tokens — nunca ia caber.

O runner então abortava sem persistir. É exatamente a lição da Fase 21 do RodoQuery — *"trava de
orçamento que joga fora trabalho já pago é pior que não ter trava"* — que eu tinha registrada e
não apliquei. Consertado: cada item é gravado com `fsync` na hora, a rodada é **retomável**, e há
`--teto-usd` que aborta **salvando**. Verificado, não presumido: a segunda execução idêntica
retomou em 0 s sem gastar um token.

## Limitações declaradas

- **n=200 estratificado**, não o conjunto completo — a estratificação 100/100 existe porque
  amostrar sem ela daria ~68% de abstenções e o lado respondível ficaria pequeno demais.
- **Um SUT só.** Todo o resultado é sobre `qwen2.5:7b`; a Fase 2b é o contraste que falta.
- **A função `localizar` é generosa com o agente**: quando a busca literal falha por reformatação
  de espaços, o crédito vai para o trecho inteiro de 400 caracteres, não para a frase exata. Está
  declarado porque rigor que eu não tenho é pior que rigor que eu não afirmo ter.
- **A guarda é assimétrica por construção** — só converte `responde` → `nao_consta`. É isso que
  torna a previsão nº 2 falsificável: ela **não pode** melhorar o lado respondível.
