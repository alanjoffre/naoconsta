"""Fase 1 — constrói o índice: fatia os 510 contratos, embute e carrega no pgvector.

Mede o que custa, porque "quanto tempo leva para indexar" é pergunta de engenharia que todo
projeto de RAG deveria responder e quase nenhum responde.
"""
import json
import time
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from naoconsta import busca, corpus

LOTE = 64                      # textos por chamada ao Ollama
SAIDA = Path(__file__).resolve().parent / "reports" / "fase1" / "indexacao.json"


def main() -> int:
    t0 = time.perf_counter()
    pedacos, consultas, textos = corpus.carregar()
    t_carga = time.perf_counter() - t0
    print(f"contratos {len(textos)}  chunks {len(pedacos):,}  consultas {len(consultas):,}  "
          f"({t_carga:.1f}s para carregar e fatiar)")

    # ---- embeddings
    t0 = time.perf_counter()
    vetores = np.empty((len(pedacos), busca.DIMS), dtype=np.float32)
    for i in range(0, len(pedacos), LOTE):
        bloco = pedacos[i:i + LOTE]
        vetores[i:i + len(bloco)] = busca.embutir([p.texto for p in bloco])
        if (i // LOTE) % 50 == 0:
            feito = i + len(bloco)
            taxa = feito / max(time.perf_counter() - t0, 1e-9)
            print(f"  embutidos {feito:6,}/{len(pedacos):,}  ({taxa:.0f} chunks/s)", flush=True)
    t_embed = time.perf_counter() - t0
    print(f"embeddings: {t_embed:.1f}s  ({len(pedacos)/t_embed:.0f} chunks/s)")

    # ---- carga
    t0 = time.perf_counter()
    with psycopg.connect(busca.DSN, autocommit=True) as con:
        con.execute(busca.ESQUEMA)
        register_vector(con)
        with con.cursor().copy(
            "COPY pedaco (contrato, ordem, inicio, fim, texto, vetor) "
            "FROM STDIN WITH (FORMAT BINARY)"
        ) as cp:
            cp.set_types(["text", "int4", "int4", "int4", "text", "vector"])
            for p, v in zip(pedacos, vetores, strict=True):
                cp.write_row((p.contrato, p.ordem, p.inicio, p.fim, p.texto, v))
        t_copy = time.perf_counter() - t0

        t0 = time.perf_counter()
        con.execute(busca.INDICE_HNSW)
        t_hnsw = time.perf_counter() - t0

        n = con.execute("SELECT count(*) FROM pedaco").fetchone()[0]
        tam = con.execute(
            "SELECT pg_size_pretty(pg_total_relation_size('pedaco'))").fetchone()[0]

    print(f"COPY: {t_copy:.1f}s   HNSW: {t_hnsw:.1f}s   linhas: {n:,}   tabela+indices: {tam}")

    art = {
        "n_contratos": len(textos), "n_chunks": len(pedacos), "n_consultas": len(consultas),
        "n_consultas_respondiveis": sum(1 for c in consultas if c.respondivel),
        "chunk": corpus.CHUNK, "sobreposicao": corpus.SOBREPOSICAO,
        "modelo_embedding": busca.MODELO_EMBED, "dims": busca.DIMS,
        "segundos": {"carga_e_fatiamento": round(t_carga, 2), "embeddings": round(t_embed, 2),
                     "copy": round(t_copy, 2), "hnsw": round(t_hnsw, 2)},
        "chunks_por_segundo": round(len(pedacos) / t_embed, 1),
        "linhas_no_banco": n, "tamanho_tabela": tam,
    }
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"artefato: {SAIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
