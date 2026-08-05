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


# Preço por milhão de tokens. NÃO tem default: modelo fora da tabela levanta erro em vez de
# reportar custo 0. É a lição da Fase 18 do RodoQuery — um relatório que publica `custo_usd: 0`
# porque o cálculo falhou em silêncio é pior que um que falha alto.
PRECOS_ANTHROPIC: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
}


def chamar_anthropic(prompt: str, modelo: str = "claude-haiku-4-5") -> tuple[str, dict]:
    """SDK oficial `anthropic`, não HTTP puro.

    Aqui a escolha é oposta à do Ollama/Groq de propósito: aqueles são serviços genéricos que
    falam HTTP, e uma dependência a menos é ganho real. Este é o SDK do próprio provedor — ele
    já traz retry com backoff para 429/5xx (`max_retries=2`), exceções tipadas e o parsing do
    `usage`. Reimplementar isso à mão seria escrever pior o que já existe.

    Decisões declaradas, ambas herdadas do pré-registro:
      - **sem structured outputs**: forçar JSON Schema responderia por decreto metade do que a
        fase mede (quantas saídas o modelo emite malformadas);
      - **sem `output_config.effort`**: o parâmetro não existe no Haiku 4.5 e seria erro.
    """
    import anthropic  # import TARDIO: quem roda só o caminho local não instala o extra [api]

    chave = os.environ.get("ANTHROPIC_API_KEY")
    if not chave:
        raise RuntimeError(
            "ANTHROPIC_API_KEY ausente. Acrescente ao ~/naoconsta/.env (chmod 600):\n"
            "  grep '^ANTHROPIC_API_KEY=' ~/rodoquery/.env >> ~/naoconsta/.env"
        )
    if modelo not in PRECOS_ANTHROPIC:
        raise ValueError(f"sem preco tabelado para '{modelo}' — acrescente em PRECOS_ANTHROPIC "
                         f"antes de rodar, para o custo nao sair zerado")

    cliente = anthropic.Anthropic(api_key=chave)
    t0 = time.perf_counter()
    try:
        r = cliente.messages.create(
            model=modelo, max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError as e:
        raise RuntimeError(f"anthropic: limite de taxa apos os retries do SDK: {e}") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"anthropic HTTP {e.status_code}: {str(e)[:200]}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"anthropic: falha de rede: {e}") from e

    entrada, saida = PRECOS_ANTHROPIC[modelo]
    ent, sai = r.usage.input_tokens, r.usage.output_tokens
    return "".join(b.text for b in r.content if b.type == "text"), {
        "provedor": "anthropic", "modelo_efetivo": r.model,
        "tokens_entrada": ent, "tokens_saida": sai,
        "segundos": round(time.perf_counter() - t0, 2),
        # A conta sai da telemetria REAL da resposta, nunca de uma estimativa a priori.
        "custo_usd": round(ent / 1e6 * entrada + sai / 1e6 * saida, 6),
        "parou_por": r.stop_reason,
    }


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


PROVEDORES = {"ollama": chamar_ollama, "groq": chamar_groq, "anthropic": chamar_anthropic}


def obter(nome: str):
    if nome not in PROVEDORES:
        raise ValueError(f"provedor '{nome}' desconhecido; use {sorted(PROVEDORES)}")
    return PROVEDORES[nome]
