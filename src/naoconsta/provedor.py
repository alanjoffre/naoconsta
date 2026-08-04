"""Provedores de LLM: um contrato só, `(prompt, modelo) -> (texto, telemetria)`.

A assinatura é IDÊNTICA à do caminho local. É o padrão do `provedor.py` do RodoQuery, e existe
pela mesma razão: se trocar de provedor exigisse mexer no `fase2_rodar.py`, a comparação entre
SUTs deixaria de ser pareada — o código do experimento mudaria junto com a variável medida.

**Groq serve modelos de peso ABERTO.** Ele dá um degrau acima do 7B local sem gastar orçamento,
mas não é um modelo de fronteira, e nenhuma leitura deve chamá-lo assim.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

GROQ_BASE = "https://api.groq.com/openai/v1"


def carregar_env(raiz: Path | None = None) -> None:
    """Leva o `.env` para o `os.environ`. Sem biblioteca, e sem nunca imprimir o valor."""
    env = (raiz or Path(__file__).resolve().parents[2]) / ".env"
    if not env.exists():
        return
    for linha in env.read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.lstrip().startswith("#"):
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def chamar_ollama(prompt: str, modelo: str = "qwen2.5:7b") -> tuple[str, dict]:
    url = os.environ.get("NAOCONSTA_OLLAMA_URL", "http://localhost:11434")
    corpo = json.dumps({"model": modelo, "prompt": prompt, "stream": False,
                        "options": {"temperature": 0, "top_k": 1, "num_predict": 400}}).encode()
    req = urllib.request.Request(f"{url}/api/generate", data=corpo,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d.get("response", ""), {
        "provedor": "ollama", "modelo_efetivo": modelo,
        "tokens_entrada": d.get("prompt_eval_count"), "tokens_saida": d.get("eval_count"),
        "segundos": round(time.perf_counter() - t0, 2), "custo_usd": 0.0,
    }


def chamar_groq(prompt: str, modelo: str = "llama-3.3-70b-versatile",
                tentativas: int = 6) -> tuple[str, dict]:
    """API compatível com a da OpenAI. Respeita o 429 lendo `retry-after` do servidor.

    A espera vem do CABEÇALHO, não de um número que eu tenha inventado: o limite medido nesta
    conta é de 12.000 tokens/minuto e o prompt tem ~3.090, então esbarrar no teto é o caso
    NORMAL, não a exceção. Backoff cego desperdiçaria metade da janela.
    """
    chave = os.environ.get("GROQ_API_KEY")
    if not chave:
        raise RuntimeError("GROQ_API_KEY ausente. Coloque em ~/naoconsta/.env (chmod 600).")
    corpo = json.dumps({
        "model": modelo, "temperature": 0, "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    espera_total = 0.0
    for tentativa in range(tentativas):
        req = urllib.request.Request(f"{GROQ_BASE}/chat/completions", data=corpo, headers={
            "Authorization": f"Bearer {chave}", "Content-Type": "application/json",
            "User-Agent": "naoconsta/0.1"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d, cab = json.loads(r.read()), dict(r.headers)
            uso = d.get("usage", {}) or {}
            return d["choices"][0]["message"]["content"], {
                "provedor": "groq", "modelo_efetivo": d.get("model", modelo),
                "tokens_entrada": uso.get("prompt_tokens"),
                "tokens_saida": uso.get("completion_tokens"),
                "segundos": round(time.perf_counter() - t0, 2),
                "espera_por_limite_s": round(espera_total, 1),
                "custo_usd": 0.0,   # camada gratuita; se virar paga, entra a conta aqui
                "restante_tokens": cab.get("x-ratelimit-remaining-tokens"),
            }
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == tentativas - 1:
                raise RuntimeError(f"groq HTTP {e.code}: "
                                   f"{(e.read() or b'').decode('utf-8', 'replace')[:200]}") from e
            cab = dict(e.headers)
            pausa = _segundos(cab.get("retry-after")) or \
                _segundos(cab.get("x-ratelimit-reset-tokens")) or 5.0
            time.sleep(min(pausa + 0.5, 70))
            espera_total += min(pausa + 0.5, 70)
    raise RuntimeError("groq: limite de tentativas esgotado")


def _segundos(v: str | None) -> float | None:
    """Aceita `7.5`, `205ms`, `1m26.4s` — os três formatos que a API devolve."""
    if not v:
        return None
    v = v.strip()
    try:
        return float(v)
    except ValueError:
        pass
    total, num = 0.0, ""
    for ch in v:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch == "m" or ch == "s":
            if num:
                total += float(num) * (60 if ch == "m" else 1)
                num = ""
    if v.endswith("ms"):
        return float(v[:-2]) / 1000
    return total or None


PROVEDORES = {"ollama": chamar_ollama, "groq": chamar_groq}


def obter(nome: str):
    if nome not in PROVEDORES:
        raise ValueError(f"provedor '{nome}' desconhecido; use {sorted(PROVEDORES)}")
    return PROVEDORES[nome]
