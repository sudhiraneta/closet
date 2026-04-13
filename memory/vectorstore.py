"""Postgres + pgvector vector store — vendored from ai-twin for standalone deployment."""

import hashlib
import json
import math
from datetime import datetime, timezone

from db.postgres import get_conn
from .chunker import Chunk
from .embeddings import EmbeddingEngine

_META_COLUMNS = {
    "source", "conversation_id", "title", "timestamp", "msg_timestamp",
    "role", "type", "pillar", "dimension", "classified",
    "cluster_id", "cluster_label",
}


def _parse_ts(value) -> str | None:
    if not value or value == "None":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return str(value)
    except (ValueError, TypeError):
        return None


def _row_to_result(row: dict) -> dict:
    metadata = {
        "source": row.get("source", ""),
        "conversation_id": row.get("conversation_id", ""),
        "title": row.get("title", ""),
        "timestamp": row["timestamp"].isoformat() if row.get("timestamp") else "",
        "msg_timestamp": row["msg_timestamp"].isoformat() if row.get("msg_timestamp") else "",
        "role": row.get("role", ""),
        "type": row.get("type", ""),
        "pillar": row.get("pillar", ""),
        "dimension": row.get("dimension", ""),
        "classified": str(row.get("classified", False)).lower(),
        "cluster_id": row.get("cluster_id", ""),
        "cluster_label": row.get("cluster_label", ""),
    }
    extra = row.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (json.JSONDecodeError, TypeError):
            extra = {}
    metadata.update(extra)

    return {
        "text": row["content"],
        "metadata": metadata,
        "distance": row.get("distance"),
        "id": row["id"],
    }


class VectorStore:

    def __init__(self):
        self.embedding_engine = EmbeddingEngine()

    @staticmethod
    def _chunk_id(text: str, metadata: dict) -> str:
        key = text + json.dumps(metadata, sort_keys=True, default=str)
        return f"chunk_{hashlib.md5(key.encode()).hexdigest()[:12]}"

    def ingest(self, chunks: list[Chunk], batch_size: int = 100) -> int:
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            seen_ids: set[str] = set()
            deduped: list[Chunk] = []
            for c in batch:
                cid = self._chunk_id(c.text, c.metadata)
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    deduped.append(c)
            batch = deduped

            texts = [c.text for c in batch]
            embeddings = self.embedding_engine.embed(texts)

            with get_conn() as conn:
                for j, chunk in enumerate(batch):
                    meta = chunk.metadata
                    emb_str = "[" + ",".join(str(float(x)) for x in embeddings[j]) + "]"
                    chunk_id = self._chunk_id(chunk.text, meta)

                    ts = _parse_ts(meta.get("timestamp", ""))
                    msg_ts = _parse_ts(meta.get("msg_timestamp", ""))
                    classified = meta.get("classified", "false")
                    if isinstance(classified, str):
                        classified = classified.lower() == "true"

                    extra = {k: v for k, v in meta.items() if k not in _META_COLUMNS}

                    conn.execute(
                        """
                        INSERT INTO chunks (
                            id, content, embedding,
                            source, conversation_id, title, timestamp, msg_timestamp,
                            role, type, pillar, dimension, classified,
                            cluster_id, cluster_label, extra
                        ) VALUES (
                            %(id)s, %(content)s, %(embedding)s::vector,
                            %(source)s, %(conversation_id)s, %(title)s, %(timestamp)s, %(msg_timestamp)s,
                            %(role)s, %(type)s, %(pillar)s, %(dimension)s, %(classified)s,
                            %(cluster_id)s, %(cluster_label)s, %(extra)s::jsonb
                        )
                        ON CONFLICT (id) DO NOTHING
                        """,
                        {
                            "id": chunk_id,
                            "content": chunk.text,
                            "embedding": emb_str,
                            "source": str(meta.get("source", "")),
                            "conversation_id": str(meta.get("conversation_id", "")),
                            "title": str(meta.get("title", "")),
                            "timestamp": ts,
                            "msg_timestamp": msg_ts,
                            "role": str(meta.get("role", "")),
                            "type": str(meta.get("type", "")),
                            "pillar": str(meta.get("pillar", "")),
                            "dimension": str(meta.get("dimension", "")),
                            "classified": classified,
                            "cluster_id": str(meta.get("cluster_id", "")),
                            "cluster_label": str(meta.get("cluster_label", "")),
                            "extra": json.dumps(extra, default=str),
                        },
                    )
                conn.commit()
            total += len(batch)

        return total

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: dict | None = None,
        where_document: dict | None = None,
        max_distance: float | None = None,
    ) -> list[dict]:
        query_embedding = self.embedding_engine.embed_single(query)
        emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"

        conditions = []
        params: dict = {"emb": emb_str, "limit": n_results}

        if where:
            for key, value in where.items():
                param_name = f"w_{key}"
                conditions.append(f"{key} = %({param_name})s")
                params[param_name] = value

        if max_distance is not None:
            conditions.append("embedding <=> %(emb)s::vector <= %(max_dist)s")
            params["max_dist"] = max_distance

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        sql = f"""
            SELECT id, content, source, conversation_id, title,
                   timestamp, msg_timestamp, role, type, pillar, dimension,
                   classified, cluster_id, cluster_label, extra,
                   embedding <=> %(emb)s::vector AS distance
            FROM chunks
            {where_clause}
            ORDER BY embedding <=> %(emb)s::vector
            LIMIT %(limit)s
        """

        with get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [_row_to_result(dict(r)) for r in rows]
