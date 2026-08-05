"""Servidor MCP: expõe a recuperação do NãoConsta como ferramenta para qualquer cliente MCP.

O MCP (Model Context Protocol) resolve um problema concreto: sem ele, cada cliente que quisesse
usar esta recuperação teria de importar `naoconsta`, subir o Postgres e falar com o Ollama. Com
ele, o cliente fala um protocolo e não sabe nada disso.

**A decisão de método que define este servidor: ele NÃO responde perguntas.** As ferramentas
devolvem trechos com procedência (contrato, offsets, similaridade) e param aí. Quem gera a
resposta é o cliente, com o próprio modelo — e é ele quem decide abster.

Isso é deliberado. Um servidor que respondesse embutiria as decisões da Fase 2 (o prompt, a
guarda, o formato) num lugar onde ninguém as mede, e a tese do projeto é sobre **medir** recusa,
não sobre escondê-la atrás de uma API. O que se exporta é o substrato verificável; o julgamento
fica onde pode ser avaliado.

Rodar:  python -m naoconsta.servidor_mcp        (transporte stdio, o default do MCP)
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from naoconsta import busca, corpus

# 30 x 400 = 12.000 caracteres — o orçamento medido na Fase 1, onde o recall é 88,1%.
# Não é número redondo: é o ponto em que a curva de recall por orçamento de texto foi validada
# no conjunto completo. Mudar aqui invalida aquela medição.
K_PADRAO = 30
K_MAXIMO = 100


@dataclass(frozen=True)
class Indice:
    """Corpus + vetores, carregados uma vez. Sem isto, cada chamada releria 82.622 vetores."""
    chunks: dict[str, list[corpus.Pedaco]]
    matriz: dict[str, np.ndarray]
    ordens: dict[str, list[int]]

    @property
    def contratos(self) -> list[str]:
        return sorted(self.chunks)


@lru_cache(maxsize=1)
def carregar_indice() -> Indice:
    import psycopg
    from pgvector.psycopg import register_vector

    pedacos, _, _ = corpus.carregar()
    chunks: dict[str, list[corpus.Pedaco]] = defaultdict(list)
    for p in pedacos:
        chunks[p.contrato].append(p)
    for k in chunks:
        chunks[k].sort(key=lambda p: p.ordem)

    # Erro de infraestrutura tem de dizer O QUE fazer. Sem isto, o cliente MCP recebia apenas
    # "connection timeout expired" — que não diz que faltava subir o Docker, e me custou uma
    # rodada de depuração procurando defeito no protocolo quando o problema era o banco parado.
    try:
        with psycopg.connect(busca.DSN, connect_timeout=10) as con:
            register_vector(con)
            linhas = con.execute(
                "SELECT contrato, ordem, vetor FROM pedaco ORDER BY contrato, ordem").fetchall()
    except psycopg.OperationalError as e:
        raise RuntimeError(
            f"pgvector inacessivel em {busca.DSN.split('password=')[0].strip()}: {e}\n"
            f"  1) o Docker Desktop esta rodando?\n"
            f"  2) o container subiu?  docker start naoconsta-pg\n"
            f"  3) o indice existe?    python fase1_indexar.py"
        ) from e

    bruto: dict[str, list] = defaultdict(list)
    ordens: dict[str, list[int]] = defaultdict(list)
    for contrato, ordem, v in linhas:
        bruto[contrato].append(np.asarray(v.to_list(), dtype=np.float32))
        ordens[contrato].append(ordem)

    if len(linhas) != len(pedacos):
        raise RuntimeError(
            f"indice desatualizado: {len(linhas):,} vetores no banco contra {len(pedacos):,} "
            f"chunks no corpus (chunk={corpus.CHUNK}/{corpus.SOBREPOSICAO}). "
            f"Rode fase1_indexar.py."
        )
    return Indice(chunks=dict(chunks),
                  matriz={k: np.vstack(v) for k, v in bruto.items()},
                  ordens=dict(ordens))


def recuperar(contrato: str, pergunta: str, k: int = K_PADRAO) -> dict:
    """Os k trechos mais próximos DENTRO de um contrato, com procedência.

    O escopo é por contrato porque o CUAD faz as mesmas 41 perguntas a todos: buscar "qual a lei
    aplicável?" no corpus inteiro é pergunta mal-posta — a resposta certa depende de qual contrato
    se está revisando (medido na Fase 1).
    """
    idx = carregar_indice()
    if contrato not in idx.chunks:
        raise ValueError(f"contrato desconhecido: {contrato!r}. Use listar_contratos.")
    k = max(1, min(int(k), K_MAXIMO))

    # `enxugar` vale +9,0 pp de recall e é aplicado aqui, não pedido ao cliente: quem chama a
    # ferramenta não deveria precisar conhecer um detalhe do corpus para obter o número medido.
    vetor = busca.embutir([corpus.enxugar(pergunta)])[0]
    ps = idx.chunks[contrato]
    sim = idx.matriz[contrato] @ vetor
    topo = np.argsort(-sim)[:k]
    return {
        "contrato": contrato,
        "k": int(k),
        "caracteres_entregues": int(sum(ps[j].fim - ps[j].inicio for j in topo)),
        "trechos": [{
            "ordem": int(ps[j].ordem),
            "inicio": int(ps[j].inicio), "fim": int(ps[j].fim),
            "similaridade": round(float(sim[j]), 4),
            "texto": ps[j].texto,
        } for j in topo],
    }


def listar_contratos(prefixo: str = "", limite: int = 50) -> dict:
    idx = carregar_indice()
    achados = [c for c in idx.contratos if c.lower().startswith(prefixo.lower())]
    return {"n_total": len(idx.contratos), "n_encontrados": len(achados),
            "contratos": achados[:max(1, min(int(limite), 500))]}


def estatisticas() -> dict:
    """A procedência do índice — para que um cliente saiba o que está consumindo."""
    idx = carregar_indice()
    n = sum(len(v) for v in idx.chunks.values())
    return {
        "contratos": len(idx.chunks), "chunks": n,
        "chunk_caracteres": corpus.CHUNK, "sobreposicao": corpus.SOBREPOSICAO,
        "modelo_embedding": busca.MODELO_EMBED, "dimensoes": busca.DIMS,
        "recall_medido": {
            "orcamento_caracteres": 12000, "k_equivalente": K_PADRAO,
            "recall": 0.8809, "ic95": [0.8740, 0.8875],
            "n_consultas": 6702, "corpus": "CUAD (CC BY 4.0)",
        },
        "ressalva": ("Recall de 88,1% significa que ~11,9% das perguntas respondiveis NAO tem a "
                     "evidencia no material entregue. Abster nesses casos e acerto pelo motivo "
                     "errado — quem consome estes trechos deveria separar as duas coisas."),
    }


FERRAMENTAS = {"recuperar": recuperar, "listar_contratos": listar_contratos,
               "estatisticas": estatisticas}


def construir_servidor():
    """Registra as ferramentas num servidor MCP. Import tardio: o extra `[mcp]` é opcional.

    A classe é `mcp.server.MCPServer` (SDK `mcp` 2.x). Eu escrevi `mcp.server.fastmcp.FastMCP`
    de memória primeiro — é a API de uma versão anterior, e o servidor morria no handshake com
    `ModuleNotFoundError`, que do lado do cliente aparecia apenas como "Connection closed".
    Peguei porque provei o servidor ponta a ponta em vez de confiar nos testes com índice falso.
    """
    from mcp.server import MCPServer

    app = MCPServer("naoconsta")

    @app.tool()
    def naoconsta_recuperar(contrato: str, pergunta: str, k: int = K_PADRAO) -> str:
        """Recupera os k trechos mais relevantes de um contrato do CUAD para uma pergunta.

        Devolve cada trecho com contrato, offsets de caractere e similaridade, para que a
        resposta possa ser auditada contra o documento. NAO responde a pergunta: se os trechos
        nao contiverem a resposta, o correto e responder que nao consta.
        """
        return json.dumps(recuperar(contrato, pergunta, k), ensure_ascii=False)

    @app.tool()
    def naoconsta_listar_contratos(prefixo: str = "", limite: int = 50) -> str:
        """Lista os contratos disponiveis, opcionalmente filtrando por prefixo do nome."""
        return json.dumps(listar_contratos(prefixo, limite), ensure_ascii=False)

    @app.tool()
    def naoconsta_estatisticas() -> str:
        """Procedencia do indice: tamanho, modelo de embedding e o recall MEDIDO, com a
        ressalva de que ~11,9% das perguntas respondiveis nao tem evidencia recuperavel."""
        return json.dumps(estatisticas(), ensure_ascii=False)

    return app


def main() -> None:
    construir_servidor().run()


if __name__ == "__main__":
    main()
