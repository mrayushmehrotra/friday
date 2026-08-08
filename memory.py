import datetime
import os

import chromadb
from chromadb.config import Settings

_CHROMA_DIR = os.path.join(os.path.dirname(__file__), ".chroma_db")
_MAX_CONTEXT = 8


def _get_collection():
    client = chromadb.PersistentClient(
        path=_CHROMA_DIR, settings=Settings(anonymized_telemetry=False)
    )
    return client.get_or_create_collection("jarvis_memory")


def store(query: str, response: str):
    col = _get_collection()
    ts = datetime.datetime.now().timestamp()
    col.add(
        documents=[f"Q: {query}\nA: {response}"],
        metadatas=[{"query": query, "response": response, "timestamp": ts}],
        ids=[f"mem_{ts}"],
    )


def search(query: str, n_results: int = _MAX_CONTEXT) -> list[str]:
    col = _get_collection()
    results = col.query(query_texts=[query], n_results=n_results)
    contexts = []
    if results["documents"] and results["documents"][0]:
        for doc in results["documents"][0]:
            contexts.append(doc)
    return contexts


def build_context(query: str) -> str:
    results = search(query)
    if not results:
        return ""
    lines = ["Here are some relevant past interactions for context:"]
    for r in results:
        lines.append(f"- {r[:400]}")
    return "\n".join(lines)
