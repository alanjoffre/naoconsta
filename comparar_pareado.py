"""Compara os DOIS SUTs restritos aos MESMOS 35 itens.

Comparar 35 itens do 70B contra os 100 do 7B seria enganoso: os subconjuntos diferem, e o teto de
recuperacao deles tambem (76,5% x 87,0%). A unica leitura honesta com um parcial e a pareada.
"""
import json
from pathlib import Path

from fase3_pontuar import acertou, recuperavel

R = Path("reports")
g = json.loads((R / "fase2/PARCIAL_decisoes_llama-3.3-70b-versatile_n200.json")
               .read_text(encoding="utf-8"))["registros"]
q = json.loads((R / "fase2/decisoes_qwen2.5_7b_n200.json")
               .read_text(encoding="utf-8"))["registros"]


def chave(r):
    return (r["contrato"], r["categoria"])


mesmos = {chave(r) for r in g}
q = [r for r in q if chave(r) in mesmos]
print(f"itens em comum: {len(g)} (70B) x {len(q)} (7B)\n")

print(f"{'':32s} {'qwen2.5:7b':>12s} {'llama-3.3-70b':>15s}")
grupos = (
    ("respondiveis", lambda r: r["respondivel"]),
    ("respondiveis c/ evidencia", lambda r: r["respondivel"] and recuperavel(r)),
    ("abstencao", lambda r: not r["respondivel"]),
)
for rot, sel in grupos:
    a = [r for r in q if sel(r)]
    b = [r for r in g if sel(r)]
    fa = sum(acertou(r, "com_guarda") for r in a) / max(len(a), 1)
    fb = sum(acertou(r, "com_guarda") for r in b) / max(len(b), 1)
    print(f"  {rot:30s} {fa:>11.1%} {fb:>14.1%}   (n={len(a)})")

ta = sum(acertou(r, "com_guarda") for r in q)
tb = sum(acertou(r, "com_guarda") for r in g)
print(f"  {'TOTAL':30s} {ta:>8d}/{len(q)} {tb:>11d}/{len(g)}")

resp_q = sum(r["sem_guarda"]["decisao"] == "responde" for r in q)
resp_g = sum(r["sem_guarda"]["decisao"] == "responde" for r in g)
bar_q = sum(r["com_guarda"]["guarda_barrou"] for r in q)
bar_g = sum(r["com_guarda"]["guarda_barrou"] for r in g)
print(f"\n  {'tentou responder':30s} {resp_q:>11d} {resp_g:>14d}")
print(f"  {'guarda barrou':30s} {bar_q:>11d} {bar_g:>14d}")
