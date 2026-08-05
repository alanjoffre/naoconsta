#!/usr/bin/env bash
# Ensaia o CI ANTES de empurrar — e o ensaio tem de divergir do runner em ZERO detalhes.
#
# Herdado da Fase 22 do RodoQuery, onde ensaiei errado tres vezes seguidas e cada vez passou
# local e falhou no runner:
#   1. `python -m pytest` (o -m poe o cwd no sys.path); o CI roda `pytest`, que nao poe;
#   2. na ARVORE DE TRABALHO, que tem gitignorados que o runner nao recebe;
#   3. num clone do HEAD com o conserto so na arvore — ensaiei o codigo antigo.
#
# Uso: bash ensaiar_ci.sh            # ensaia o ultimo commit
#      bash ensaiar_ci.sh --negativo # + controle negativo: sem `pythonpath`, a trava DEVE reprovar
set -u
ORIGEM="$(cd "$(dirname "$0")" && pwd)"
ALVO=/tmp/ensaio_naoconsta
NEG="${1:-}"

if [ -n "$(git -C "$ORIGEM" status --porcelain)" ]; then
  echo "AVISO: ha mudancas nao commitadas — o clone NAO as vera (foi o erro #3)."
  git -C "$ORIGEM" status --short
  echo
fi

rm -rf "$ALVO"
git clone -q "$ORIGEM" "$ALVO" || exit 9
cd "$ALVO" || exit 9
python3 -m venv .venv >/dev/null
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[test]" || exit 9
export PATH="$ALVO/.venv/bin:$PATH"
# O runner nao tem o corpus CUAD (26,8 MB de texto, fora do repo): apontar para lugar nenhum.
export NAOCONSTA_CUAD_DIR=/nao/existe
echo "ensaiando $(git log --oneline -1)"

if [ "$NEG" = "--negativo" ]; then
  echo
  echo "=== CONTROLE NEGATIVO: sem \`pythonpath\`, a trava de coleta DEVE reprovar ==="
  sed -i '/^pythonpath = \["\."\]$/d' pyproject.toml
  python verificar_coleta.py >/dev/null 2>&1
  rc=$?
  [ "$rc" -ne 0 ] && echo "  OK    trava reprovou (rc=$rc), como tem de reprovar" \
                  || echo "  FALHA trava APROVOU o estado quebrado — falso negativo"
  git checkout -q pyproject.toml
fi

falhou=0
passo() {
  local rotulo="$1"; shift
  local saida; saida="$("$@" 2>&1)"; local rc=$?
  [ "$rc" -ne 0 ] && falhou=1
  printf '%-26s rc=%d\n' "$rotulo" "$rc"
  [ "$rc" -ne 0 ] && echo "$saida" | tail -20
  return 0
}

echo
echo "=== sequencia do .github/workflows/ci.yml ==="
# Esta lista TEM de espelhar .github/workflows/ci.yml passo a passo. Ja errei aqui: acrescentei
# a auditoria de fidelidade ao CI e esqueci de acrescentar ao ensaio, que passou a aprovar uma
# sequencia mais curta que a do alvo — o mesmo defeito que o ensaio existe para evitar.
passo "1. Lint (ruff)"       ruff check .
passo "2. Coleta completa"   python verificar_coleta.py
passo "3. Testes"            pytest -q
passo "4. Auditoria de fidelidade" python auditar_documentacao.py

echo
[ "$falhou" -eq 0 ] && echo "ENSAIO VERDE — mas o veredito e a execucao do Actions, nao esta." \
                    || { echo "ENSAIO VERMELHO — nao empurre."; exit 1; }
