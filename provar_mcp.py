"""Prova ponta a ponta: sobe o servidor MCP como SUBPROCESSO e fala o protocolo com ele.

Testes com indice falso provam a LOGICA. Isto prova que o servidor EXISTE: handshake, listagem
de ferramentas e uma chamada real contra o pgvector com 82.622 vetores — a diferenca entre "a
funcao retorna" e "um cliente MCP consegue usar".

Fica versionado porque os 68 testes passavam enquanto o servidor NAO SUBIA: eu escrevi
`mcp.server.fastmcp.FastMCP` de memoria, que e a API de uma versao anterior do SDK, e do lado do
cliente isso aparecia apenas como "Connection closed". Teste com dependencia injetada nao
substitui subir o processo de verdade.
"""
import asyncio
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def ler(r, rotulo: str):
    """Nunca explodir em json.loads: se a ferramenta errou, o texto E o diagnostico."""
    bruto = r.content[0].text if r.content else ""
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        print(f"\n!! {rotulo} nao devolveu JSON (isError={bool(r.is_error)}):")
        print(f"   {bruto[:400]}")
        raise SystemExit(1) from None



async def main() -> int:
    params = StdioServerParameters(command=".venv/bin/python",
                                   args=["-m", "naoconsta.servidor_mcp"])
    async with stdio_client(params) as (entrada, saida):
        async with ClientSession(entrada, saida) as s:
            await s.initialize()
            print("handshake: OK")

            fs = await s.list_tools()
            print(f"ferramentas expostas: {len(fs.tools)}")
            for t in fs.tools:
                print(f"  {t.name:30s} {(t.description or '').splitlines()[0][:70]}")

            r = await s.call_tool("naoconsta_estatisticas", {})
            e = ler(r, "estatisticas")
            print(f"\nindice: {e['contratos']} contratos, {e['chunks']:,} chunks, "
                  f"chunk={e['chunk_caracteres']}/{e['sobreposicao']}")
            print(f"recall declarado: {e['recall_medido']['recall']:.1%} "
                  f"em {e['recall_medido']['orcamento_caracteres']:,} chars")

            r = await s.call_tool("naoconsta_listar_contratos", {"limite": 1})
            alvo = ler(r, "listar")["contratos"][0]

            r = await s.call_tool("naoconsta_recuperar", {
                "contrato": alvo,
                "pergunta": 'Highlight the parts (if any) of this contract related to '
                            '"Governing Law" that should be reviewed by a lawyer. '
                            'Details: Which state/country law governs the contract?',
                "k": 3})
            d = ler(r, "recuperar")
            print(f"\nrecuperar em {alvo[:44]}...")
            print(f"  {d['k']} trechos, {d['caracteres_entregues']:,} caracteres")
            for t in d["trechos"]:
                trecho = " ".join(t["texto"].split())[:88]
                print(f"  sim={t['similaridade']:.3f} [{t['inicio']}:{t['fim']}] {trecho}")

            r = await s.call_tool("naoconsta_recuperar",
                                  {"contrato": "nao_existe", "pergunta": "x"})
            print(f"\ncontrato invalido -> erro propagado: {bool(r.is_error)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
