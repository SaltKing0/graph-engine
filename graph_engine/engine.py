"""Ingest: text in → node + embedding + edge suggestions out."""

from __future__ import annotations

from .model import Node
from .store import Store
from .embedder import get_embedder
from .suggester import suggest_edges


class Engine:
    """The growth loop as a class — store + embedder bundled."""

    def __init__(self, store: Store, embedder=None):
        self.store = store
        self.embedder = embedder if embedder is not None else get_embedder()

    def ingest(self, text: str) -> tuple[Node, list]:
        text = text.strip()
        if not text:
            raise ValueError("Empty text cannot be ingested.")
        node = Node(text=text)
        vec = self.embedder.embed(text)
        self.store.add_node(node)
        candidates = {
            n.id: self.embedder.embed(n.text)
            for n in self.store.nodes if n.id != node.id
        }
        edges = suggest_edges(node.id, vec, candidates)
        for e in edges:
            self.store.add_edge(e)
        return node, edges


def main() -> None:
    import sys
    embedder_name = "hash" if "--hash" in sys.argv else "st"
    args = [a for a in sys.argv[1:] if a != "--hash"]
    if "-f" in args:
        path = args[args.index("-f") + 1]
        text = open(path, encoding="utf-8").read()
    elif "-" in args:
        text = sys.stdin.read()
    else:
        text = " ".join(args)
    if not text.strip():
        print("Nothing to ingest. Usage: python -m graph_engine <text|->")
        sys.exit(1)
    store = Store()
    engine = Engine(store, get_embedder(embedder_name))
    node, edges = engine.ingest(text)
    print(f"Node {node.id}: {node.text}")
    for e in edges:
        print(f"  Suggestion: --[{e.kind}]--> {e.target} (pending)")


if __name__ == "__main__":
    main()
