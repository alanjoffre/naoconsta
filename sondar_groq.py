"""Sonda a conta Groq: quais modelos ela enxerga e quais limites de fato valem.

Nada aqui é presumido. O catálogo de um provedor muda, e limite de plano varia por conta — então
os dois saem da API, e os limites saem dos CABEÇALHOS de uma chamada real, não da documentação.

Custo: uma requisição de ~10 tokens. Nenhuma decisão de gasto é tomada por este script.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://api.groq.com/openai/v1"
RAIZ = Path(__file__).resolve().parent
SAIDA = RAIZ / "reports" / "fase2" / "groq_conta.json"


def carregar_env() -> str:
    """Lê o .env sem depender de biblioteca — e sem imprimir a chave em lugar nenhum."""
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    chave = os.environ.get("GROQ_API_KEY", "")
    if not chave:
        raise SystemExit("GROQ_API_KEY ausente — ver .env")
    return chave


def _req(url: str, chave: str, corpo: bytes | None = None):
    """Devolve (status, cabecalhos, dados). Corpo que nao e JSON NAO explode: vira texto cru.

    Erro de provedor costuma vir em HTML (WAF, proxy, pagina de erro) e um `json.loads` cego
    transforma um 401 legivel num traceback que nao diz nada.
    """
    r = urllib.request.Request(url, data=corpo, headers={
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json",
        "User-Agent": "naoconsta/0.1",
    })
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            bruto, status, cab = resp.read(), resp.status, dict(resp.headers)
    except urllib.error.HTTPError as e:
        bruto, status, cab = (e.read() or b""), e.code, dict(e.headers)
    except urllib.error.URLError as e:
        return 0, {}, {"erro_de_rede": str(e.reason)}
    try:
        return status, cab, json.loads(bruto)
    except json.JSONDecodeError:
        return status, cab, {"corpo_nao_json": bruto.decode("utf-8", "replace")[:400]}


def main() -> int:
    chave = carregar_env()

    st, _, dados = _req(f"{BASE}/models", chave)
    if st != 200:
        print(f"falha ao listar modelos: HTTP {st} — {json.dumps(dados)[:200]}")
        return 1
    modelos = sorted(dados.get("data", []), key=lambda m: m["id"])
    print(f"modelos visiveis para esta conta: {len(modelos)}\n")
    print(f"  {'id':44s} {'contexto':>9s} {'saida max':>10s}")
    for m in modelos:
        print(f"  {m['id']:44s} {str(m.get('context_window', '?')):>9s} "
              f"{str(m.get('max_completion_tokens', '?')):>10s}")

    # Chamada minima so para LER OS CABECALHOS de limite — e o unico jeito honesto de saber
    # o que vale para esta conta.
    alvo = next((m["id"] for m in modelos if "llama" in m["id"] and "70b" in m["id"]),
                modelos[0]["id"] if modelos else None)
    corpo = json.dumps({"model": alvo, "max_tokens": 5,
                        "messages": [{"role": "user", "content": "ok"}]}).encode()
    st, cab, resp = _req(f"{BASE}/chat/completions", chave, corpo)
    print(f"\nchamada de teste em `{alvo}`: HTTP {st}")
    limites = {k: v for k, v in cab.items() if "ratelimit" in k.lower()}
    for k in sorted(limites):
        print(f"  {k:34s} {limites[k]}")
    if st != 200:
        print(f"  corpo: {json.dumps(resp)[:300]}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({
        "n_modelos": len(modelos),
        "modelos": [{k: m.get(k) for k in ("id", "context_window", "max_completion_tokens",
                                           "owned_by")} for m in modelos],
        "modelo_testado": alvo, "status_teste": st, "limites": limites,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nartefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
