"""Chunk dataclass and metadata helpers."""

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    metadata: dict


DEFAULT_METADATA = {
    "source": "", "conversation_id": "", "title": "", "timestamp": "",
    "msg_timestamp": "", "role": "", "type": "", "pillar": "",
    "dimension": "", "classified": "false",
}


def _ensure_metadata(metadata: dict) -> dict:
    result = {**DEFAULT_METADATA, **metadata}
    for key, value in result.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, (list, dict)):
            import json
            result[key] = json.dumps(value)
    return result
