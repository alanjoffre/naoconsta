"""Transforma um parcial `.jsonl` no artefato `.json` que o pontuador lê. Não interpreta nada.

O runner grava cada item na hora (com `fsync`) e só escreve o `.json` consolidado quando o laço
termina. Quando a rodada para no meio — teto diário do provedor, rede, `--teto-usd` — o trabalho
já pago fica no `.jsonl` e precisa deste passo para virar artefato pontuável.

O nome de saída leva `PARCIAL_` de propósito: um artefato incompleto não pode se parecer com um
completo na listagem de `reports/`.
"""
import json
import sys
from pathlib import Path


def main() -> int:
    p = Path(sys.argv[1])
    regs, tel = [], []
    for linha in p.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            d = json.loads(linha)
            regs.append(d["registro"])
            tel.append(d["telemetria"])
    if not regs:
        print("parcial vazio — nada a consolidar")
        return 1

    saida = p.parent / p.name.replace("parcial_", "PARCIAL_decisoes_").replace(".jsonl", ".json")
    saida.write_text(json.dumps({
        "modelo": tel[0].get("modelo_efetivo"), "provedor": tel[0].get("provedor"),
        "k": 30, "chunk": 400, "sobreposicao": 75,
        "PARCIAL": True, "n_planejado": 200,
        "telemetria": {
            "custo_usd_total": round(sum(t.get("custo_usd") or 0 for t in tel), 6),
            "tokens_entrada": sum(t.get("tokens_entrada") or 0 for t in tel),
            "tokens_saida": sum(t.get("tokens_saida") or 0 for t in tel),
        },
        "registros": regs,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"{len(regs)} itens -> {saida.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
