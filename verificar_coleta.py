"""Trava de COLETA: nenhum teste pode sumir em silêncio.

Por que existe. O CI instalava `.[dev]`, mas `tests/test_servico*.py` importam `fastapi`, que
vive no extra `[serve]`. A coleta do pytest quebrava, o build ficava vermelho — e ficou por 32
execuções seguidas (12 dias) sem ninguém ler o log. O modo de falha PERIGOSO é o simétrico: se
aqueles arquivos tivessem um `pytest.importorskip`, a suíte ficaria VERDE com testes a menos, e o
badge diria "passando" sobre uma cobertura menor. Verde com teste faltando é pior que vermelho.

POR QUE EM SUBPROCESSO, e não `pytest.main()`. A primeira versão desta trava rodava a coleta
in-process, a partir da raiz do repositório — e por isso a raiz estava no `sys.path` de graça. Ela
passou no CI enquanto o `pytest` do passo seguinte falhava, porque o console script `pytest` NÃO
põe o cwd no `sys.path` (só `python -m pytest` põe). A trava deu falso negativo sobre exatamente a
classe de defeito que existe para pegar. Agora ela invoca o MESMO executável `pytest`, do mesmo
diretório, que o CI invoca: uma trava que não reproduz a invocação do CI não é trava.

Afirma três coisas, todas falseáveis:
  1. a coleta não tem erro nenhum;
  2. TODO arquivo `tests/test_*.py` contribuiu com pelo menos um teste;
  3. o total não caiu abaixo do piso declarado abaixo.

O piso é `>=`: acrescentar teste passa sozinho, só a REMOÇÃO exige mexer aqui — e mexer é o
ponto, porque aí a queda vira decisão explícita, com autor e commit.
"""
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
# Piso medido em 2026-08-03 (Fase 22). Só desça este número deliberadamente, no mesmo commit que
# remove os testes, explicando no corpo da mensagem por quê.
PISO_TOTAL = 68
_ITEM = re.compile(r"^(tests[/\\][\w.]+\.py)::")


def main() -> int:
    exe = shutil.which("pytest")
    if exe is None:
        print("pytest nao encontrado no PATH — o CI usa o console script, entao isto e erro.")
        return 1

    r = subprocess.run(
        [exe, "--collect-only", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
    )
    saida = r.stdout + r.stderr
    itens = [m.group(1).replace("\\", "/") for ln in saida.splitlines() if (m := _ITEM.match(ln))]

    arquivos = sorted(p.name for p in (REPO / "tests").glob("test_*.py"))
    por_arquivo = Counter(c.split("/")[-1] for c in itens)
    vazios = [a for a in arquivos if por_arquivo[a] == 0]

    print(f"invocacao: {exe} --collect-only  (mesma do CI)")
    print(f"arquivos de teste no disco: {len(arquivos)}    testes coletados: {len(itens)}")
    for a in arquivos:
        print(f"  {'OK   ' if por_arquivo[a] else 'VAZIO'}  {a:34s} {por_arquivo[a]:4d}")

    problemas = []
    if r.returncode != 0:
        cauda = "\n      ".join([ln for ln in saida.splitlines() if ln.strip()][-6:])
        problemas.append(f"a coleta terminou com erro (rc={r.returncode}):\n      {cauda}")
    if vazios:
        problemas += [f"arquivo coletou ZERO testes (import quebrado? extra faltando?) -> {a}"
                      for a in vazios]
    if len(itens) < PISO_TOTAL:
        problemas.append(f"total {len(itens)} abaixo do piso declarado {PISO_TOTAL}")

    if problemas:
        print("\nCOLETA REPROVADA:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print(f"\nCOLETA OK — {len(itens)} testes, piso {PISO_TOTAL}, 0 arquivos vazios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
