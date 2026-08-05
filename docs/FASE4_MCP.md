# Fase 4 — servidor MCP, e o servidor que não responde

A recuperação da Fase 1 exposta como servidor **MCP** (Model Context Protocol). Sem ele, qualquer
cliente que quisesse usá-la teria de importar `naoconsta`, subir o Postgres e falar com o Ollama.
Com ele, o cliente fala um protocolo e não sabe nada disso.

```bash
python -m naoconsta.servidor_mcp     # transporte stdio, o default do MCP
python provar_mcp.py                 # prova ponta a ponta contra o servidor real
```

## A decisão que define este servidor: ele não responde perguntas

As três ferramentas devolvem **trechos com procedência** — contrato, offsets de caractere,
similaridade — e param aí. Quem gera a resposta é o cliente, com o próprio modelo, e é ele quem
decide abster.

Isso é deliberado. Um servidor que respondesse embutiria as decisões da Fase 2 — o prompt, a
guarda, o formato — num lugar onde **ninguém as mede**. A tese do projeto é sobre *medir* recusa,
não sobre escondê-la atrás de uma API. O que se exporta é o substrato verificável; o julgamento
fica onde pode ser avaliado.

| ferramenta | devolve |
|---|---|
| `naoconsta_recuperar` | k trechos de **um** contrato, com offsets e similaridade |
| `naoconsta_listar_contratos` | os 510 contratos, com filtro por prefixo |
| `naoconsta_estatisticas` | procedência do índice **e o teto declarado** |

Duas escolhas que evitam repassar armadilha ao cliente:

- **`enxugar` é aplicado aqui**, não pedido a quem chama. Ele vale +9,0 pp de recall (Fase 1);
  exigir que o cliente conheça um detalhe do corpus para obter o número medido seria entregar
  menos recall a quem não leu a documentação.
- **`estatisticas` declara o teto**: recall de 88,1% significa que **~11,9% das perguntas
  respondíveis não têm a evidência no material entregue**. Sem esse aviso no próprio protocolo,
  quem consome os trechos lê abstenção como acerto.

`k` é limitado nos dois extremos (1 a 100). `k=0` devolveria nada; `k` enorme devolveria o
contrato inteiro — que é exatamente o modo de falha medido na Fase 1b: **mais texto compra recall
e paga em abstenção**.

## Os 68 testes passavam com o servidor quebrado

Escrevi as ferramentas, escrevi 11 testes com um índice falso injetado — sem Postgres, sem Ollama,
sem corpus — e tudo passou. **O servidor não subia.**

Eu tinha escrito `mcp.server.fastmcp.FastMCP` de memória: é a API de uma versão anterior do SDK,
e o instalado é o `mcp` 2.0, onde a classe é `mcp.server.MCPServer`. O processo morria com
`ModuleNotFoundError` — e do lado do cliente isso aparecia apenas como **"Connection closed"**.

> Teste com dependência injetada prova a **lógica**. Ele não prova que o processo sobe, que o
> handshake fecha, nem que o cliente enxerga as ferramentas. São garantias diferentes, e a
> primeira não implica a segunda.

Por isso o `provar_mcp.py` ficou versionado: ele sobe o servidor como **subprocesso** e fala o
protocolo de verdade.

## Três defeitos que só a prova real expôs

| defeito | como aparecia | causa |
|---|---|---|
| API do SDK errada | `Connection closed` | `FastMCP` escrito de memória; o SDK 2.0 usa `MCPServer` |
| Postgres inacessível | `connection timeout expired` | **o Docker Desktop não estava rodando** |
| Ollama parado | `urlopen error [Errno 110]` | ele cai junto com a sessão — precisa de `setsid` |

Nenhum dos três é defeito de lógica, e **nenhum dos três seria pego pelos testes**. Os dois
últimos também não eram do meu código — mas apareceram como mensagens que não diziam o que fazer.

Consertei a que era minha responsabilidade: o servidor agora falha com instrução em vez de
`connection timeout`.

```
pgvector inacessivel em host=localhost port=5433 user=postgres:
  1) o Docker Desktop esta rodando?
  2) o container subiu?  docker start naoconsta-pg
  3) o indice existe?    python fase1_indexar.py
```

*Erro de infraestrutura tem de dizer o que fazer.* O opaco me custou uma rodada inteira de
depuração procurando defeito no protocolo quando o problema era um container parado.

## Meu próprio provador falhou três vezes antes de provar algo

Vale registrar, porque o padrão se repete no projeto:

1. **`json.loads` cego** — quando a ferramenta devolvia erro, o provador explodia com
   `JSONDecodeError` em vez de mostrar a mensagem. Consertado: erro que não é JSON vira
   diagnóstico impresso.
2. **Colisão de nome** — a função auxiliar `ler` e a variável do stream `ler` no mesmo escopo;
   a local sombreava a função e dava `'MemoryObjectReceiveStream' object is not callable`.
3. **`isError` em vez de `is_error`** — o SDK 2.0 usa snake_case.

Os três são meus, e os três só apareceram porque insisti em rodar o processo real.

## Limitações declaradas

- **Transporte stdio apenas.** É o default do MCP e o que clientes locais usam; HTTP/SSE não foi
  exercitado.
- **Sem autenticação.** O servidor assume execução local, como o transporte stdio implica.
  Expor por rede exigiria autenticação, que não está aqui.
- **O índice carrega inteiro na memória** (82.622 × 768 floats ≈ 254 MB) na primeira chamada.
  Aceitável para uso local; não é desenho de serviço multi-inquilino.
- **Nenhum teste do servidor roda no CI** — os 11 testes de lógica rodam, mas a prova ponta a
  ponta precisa de Postgres e Ollama, que o runner não tem. Ela é manual e está declarada assim.
