"""Mede TODOS os limites por modelo — inclusive o DIARIO, que eu deixei passar.

A primeira sondagem leu `x-ratelimit-limit-tokens` (por minuto) e concluiu que ele era a
restricao que manda. Nao era: ha um teto por DIA (TPD) que so aparece quando se estoura, e a
rodada de 200 consultas morreu nele depois de ~35 itens.

Licao: `x-ratelimit-*` sem sufixo NAO diz a janela. Medir um limite e ler TODOS os cabecalhos,
nao o primeiro que casa com o nome que eu esperava.
"""
import json
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from pathlib import Path

from naoconsta.provedor import GROQ_BASE, carregar_env

CANDIDATOS = [
    "llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b", "llama-3.1-8b-instant",
]
SAIDA = Path(__file__).resolve().parent / "reports" / "fase2" / "groq_limites.json"


def sondar(modelo: str, chave: str) -> dict:
    corpo = json.dumps({"model": modelo, "max_tokens": 1,
                        "messages": [{"role": "user", "content": "ok"}]}).encode()
    # O User-Agent NAO e enfeite: sem ele o urllib manda `Python-urllib/3.12` e o Cloudflare
    # devolve 403 `error code: 1010` (bloqueio por assinatura do cliente). Foi o que me fez
    # confundir WAF com cota esgotada. Mesma armadilha ja registrada na base do CFPB.
    req = urllib.request.Request(f"{GROQ_BASE}/chat/completions", data=corpo, headers={
        "Authorization": f"Bearer {chave}", "Content-Type": "application/json",
        "User-Agent": "naoconsta/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            cab, st = dict(r.headers), r.status
    except urllib.error.HTTPError as e:
        cab, st = dict(e.headers), e.code
    lim = {k.lower(): v for k, v in cab.items() if "ratelimit" in k.lower()}
    return {"status": st, **lim}


def main() -> int:
    carregar_env()
    import os
    chave = os.environ["GROQ_API_KEY"]
    art = {}
    print(f"{'modelo':26s} {'st':>4s} {'req/janela':>11s} {'tok/janela':>11s} "
          f"{'resta tok':>10s} {'reset tok':>12s}")
    for m in CANDIDATOS:
        d = sondar(m, chave)
        art[m] = d
        print(f"{m:26s} {d['status']:>4d} "
              f"{d.get('x-ratelimit-limit-requests', '?'):>11s} "
              f"{d.get('x-ratelimit-limit-tokens', '?'):>11s} "
              f"{d.get('x-ratelimit-remaining-tokens', '?'):>10s} "
              f"{d.get('x-ratelimit-reset-tokens', '?'):>12s}")

    print("\ncabecalhos completos do primeiro modelo (para nao perder nenhum de novo):")
    for k, v in sorted(art[CANDIDATOS[0]].items()):
        print(f"  {k:38s} {v}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
