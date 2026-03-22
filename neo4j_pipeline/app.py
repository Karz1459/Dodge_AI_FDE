import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .graph_qa import answer_question, get_neo4j_graph


app = FastAPI(title="Order Flow Graph Explorer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str


class GraphRequest(BaseModel):
    id: str
    label: str | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    properties: Dict[str, Any]


class GraphEdge(BaseModel):
    id: str
    type: str
    source: str
    target: str


class GraphResponse(BaseModel):
    center: GraphNode | None
    nodes: List[GraphNode]
    edges: List[GraphEdge]


class FullGraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]

_DOMAIN_KEYWORDS = [
    "order",
    "sales order",
    "delivery",
    "invoice",
    "billing",
    "payment",
    "journal entry",
    "customer",
    "business partner",
    "product",
    "material",
    "address",
]


def _is_in_domain(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in _DOMAIN_KEYWORDS)


@app.post("/api/chat", response_model=ChatResponse)
def chat_post(req: ChatRequest) -> ChatResponse:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty")

    if not _is_in_domain(req.question):
        return ChatResponse(
            answer="This system only supports queries related to orders, deliveries, invoices, payments, customers, and products."
        )

    try:
        answer = answer_question(req.question)
        return ChatResponse(answer=str(answer))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat", response_model=ChatResponse)
def chat_get(question: str = Query(..., description="Your question")) -> ChatResponse:
    if not question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty")

    if not _is_in_domain(question):
        return ChatResponse(
            answer="This system only supports queries related to orders, deliveries, invoices, payments, customers, and products."
        )

    try:
        answer = answer_question(question)
        return ChatResponse(answer=str(answer))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/graph", response_model=GraphResponse)
def graph_neighborhood(req: GraphRequest) -> GraphResponse:
    try:
        graph = get_neo4j_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j connection failed: {e}")

    params: Dict[str, Any] = {"id": req.id}

    if req.label:
        match = f"MATCH (c:{req.label} {{id: $id}})"
    else:
        match = "MATCH (c {id: $id})"

    cypher = match + "\nOPTIONAL MATCH (c)-[r]-(n)\nRETURN c, r, n LIMIT 200"

    try:
        rows: List[Dict[str, Any]] = graph.query(cypher, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    center_node: GraphNode | None = None
    nodes: Dict[str, GraphNode] = {}
    edges: Dict[str, GraphEdge] = {}

    for row in rows:
        c = row.get("c")
        r = row.get("r")
        n = row.get("n")

        if c is not None:
            cid = c.get("id")
            if cid and cid not in nodes:
                node = GraphNode(
                    id=str(cid),
                    label=":".join(getattr(c, "_labels", []) or ["Node"]),
                    properties=dict(c),
                )
                nodes[node.id] = node
                center_node = node

        if n is not None:
            nid = n.get("id")
            if nid and nid not in nodes:
                node = GraphNode(
                    id=str(nid),
                    label=":".join(getattr(n, "_labels", []) or ["Node"]),
                    properties=dict(n),
                )
                nodes[node.id] = node

        if r is not None and c is not None and n is not None:
            source = c.get("id")
            target = n.get("id")

            if not source or not target:
                continue

            rid = getattr(r, "id", None) or f"{source}|{type(r).__name__}|{target}"
            rid = str(rid)

            if rid not in edges:
                etype = getattr(r, "type", None) or type(r).__name__

                edges[rid] = GraphEdge(
                    id=rid,
                    type=str(etype),
                    source=str(source),
                    target=str(target),
                )

    return GraphResponse(
        center=center_node,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
    )


@app.get("/api/full-graph", response_model=FullGraphResponse)
def full_graph() -> FullGraphResponse:
    """Return a capped view of the full graph (nodes + edges).

    For performance reasons this is limited to ~2000 relationships.
    """

    try:
        graph = get_neo4j_graph()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Neo4j connection failed: {e}")

    # Limit the number of relationships for responsiveness
    cypher = "MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 2000"

    try:
        rows: List[Dict[str, Any]] = graph.query(cypher)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    nodes: Dict[str, GraphNode] = {}
    edges: Dict[str, GraphEdge] = {}

    for row in rows:
        a = row.get("a")
        r = row.get("r")
        b = row.get("b")

        for n in (a, b):
            if n is None:
                continue
            nid = n.get("id")
            if not nid or nid in nodes:
                continue
            node = GraphNode(
                id=str(nid),
                label=":".join(getattr(n, "_labels", []) or ["Node"]),
                properties=dict(n),
            )
            nodes[node.id] = node

        if r is not None and a is not None and b is not None:
            source = a.get("id")
            target = b.get("id")
            if not source or not target:
                continue

            rid = getattr(r, "id", None) or f"{source}|{type(r).__name__}|{target}"
            rid = str(rid)
            if rid in edges:
                continue

            etype = getattr(r, "type", None) or type(r).__name__
            edges[rid] = GraphEdge(
                id=rid,
                type=str(etype),
                source=str(source),
                target=str(target),
            )

    return FullGraphResponse(nodes=list(nodes.values()), edges=list(edges.values()))

@app.get("/")
def root() -> Dict[str, str]:
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)

    return {
        "status": "ok",
        "message": "Order Flow Graph Explorer API is running",
    }