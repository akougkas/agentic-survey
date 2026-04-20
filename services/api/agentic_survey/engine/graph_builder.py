from dataclasses import dataclass, field


@dataclass(slots=True)
class GraphDelta:
    add_nodes: list[dict[str, str]] = field(default_factory=list)
    add_edges: list[dict[str, str]] = field(default_factory=list)
    light_up: list[str] = field(default_factory=list)


def build_graph_delta(concepts: list[dict[str, str]]) -> GraphDelta:
    nodes = [{"id": concept["label"], "label": concept["label"]} for concept in concepts]
    return GraphDelta(add_nodes=nodes)
