#!/usr/bin/env bash
# Estado das rodadas. Fica versionado porque eu ja errei 3x checando isso de forma inline:
# `pgrep -f <padrao>` casa com a PROPRIA linha de comando do checador quando o padrao e digitado
# no shell. Dentro de um script, a linha de comando do processo e so "bash ver_estado.sh".
cd "$HOME/naoconsta" || exit 9

echo "=== rodadas em andamento ==="
if pgrep -u "$USER" -f "venv/bin/python fase" > /dev/null; then
  pgrep -u "$USER" -af "venv/bin/python fase" | sed 's/^/  /'
else
  echo "  nenhuma"
fi

echo
echo "=== logs ==="
for f in /tmp/fase2.log /tmp/groq70b.log /tmp/reindex.log; do
  [ -f "$f" ] && printf "  %-14s %s\n" "$(basename "$f")" "$(tail -1 "$f" | cut -c1-92)"
done

echo
echo "=== parciais retomaveis ==="
ls -1 reports/fase2/parcial_*.jsonl 2>/dev/null | while read -r p; do
  printf "  %-46s %s itens\n" "$(basename "$p")" "$(wc -l < "$p")"
done || true
[ -z "$(ls -1 reports/fase2/parcial_*.jsonl 2>/dev/null)" ] && echo "  nenhum"

echo
echo "=== artefatos finais ==="
find reports -name "*.json" -newermt "-3 days" -printf "  %-58p %6s KB\n" 2>/dev/null | sort
