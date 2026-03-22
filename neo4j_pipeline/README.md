# Dodge AI – Order‑to‑Cash Graph + LLM

This project builds a realistic order‑to‑cash **business graph** in Neo4j from JSONL tables (orders, deliveries, invoices, payments, customers, products, AR, plants, etc.) and exposes it through:

- A Python **ETL loader** (`load_jsonl_to_neo4j.py`).
- An **LLM QA layer** (`graph_qa.py`) using LangChain + Groq to translate questions → Cypher → answers.
- A **FastAPI backend** (`app.py`) that provides chat and graph APIs.
- A **Cytoscape.js web UI** (`static/index.html`) for interactive graph visualization + chat.

Everything is wired end‑to‑end so you can ask business questions like:

- "For sales order 740506, show items, deliveries, invoices, AR and payments."
- "Identify sales orders that are delivered but not billed, or billed without delivery."

and see both a natural‑language answer and the corresponding neighborhood in the graph.

---

## 1. Project layout

At the top level (simplified):

```text
Dodge_AI/
  data/                     # JSONL input tables
    business_partners/
    business_partner_addresses/
    customer_company_assignments/
    customer_sales_area_assignments/
    products/
    product_descriptions/
    plants/
    product_plants/
    product_storage_locations/
    sales_order_headers/
    sales_order_items/
    sales_order_schedule_lines/
    outbound_delivery_headers/
    outbound_delivery_items/
    billing_document_headers/
    billing_document_items/
    payments_accounts_receivable/
    journal_entry_items_accounts_receivable/

  neo4j_pipeline/
    load_jsonl_to_neo4j.py  # JSONL → Neo4j loader
    graph_qa.py             # LLM QA over Neo4j
    app.py                  # FastAPI app (chat + graph APIs)
    README.md

  static/
    index.html              # Cytoscape.js UI (graph + chat)
```

The `data/` folders and file names are aligned with the SAP‑like sample datasets; adjust only if your dataset structure differs.

---

## 2. Installation & prerequisites

Create/activate a virtual environment, then install dependencies (example using `pip`):

```bash
pip install neo4j langchain langchain-community langchain-groq fastapi uvicorn python-dotenv
```

You also need:

- A running **Neo4j** instance (e.g. Neo4j Desktop or Docker) with Bolt or neo4j protocol enabled.
- A **Groq API key** for LLM inference.

---

## 3. Configure environment

Neo4j connection (with defaults in parentheses):

- `NEO4J_URI` (default: `bolt://localhost:7687` or `neo4j://localhost:7687`)
- `NEO4J_USER` (default: `neo4j`)
- `NEO4J_PASSWORD` (default: `password`)

Groq LLM:

- `GROQ_API_KEY` – your Groq API key.

Example on Windows PowerShell:

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "password"
$env:GROQ_API_KEY = "your_groq_api_key"
```

The code uses `python-dotenv`, so you can optionally put these into a `.env` file at the project root.

---

## 4. Loading JSONL data into Neo4j

The loader script [neo4j_pipeline/load_jsonl_to_neo4j.py](neo4j_pipeline/load_jsonl_to_neo4j.py) takes JSONL tables and builds a rich graph.

### 4.1 What gets created

**Nodes (labels):**

- `BusinessPartner`, `BusinessPartnerAddress`, `CustomerCompany`, `CustomerSalesArea`
- `Product`, `ProductDescription`, `Plant`, `ProductPlant`, `ProductStorageLocation`
- `SalesOrder`, `SalesOrderItem`, `SalesOrderScheduleLine`
- `Delivery` (outbound delivery header)
- `BillingDocument`, `BillingItem`
- `Payment` (payments AR)
- `ARItem` (journal entry items AR)

All nodes have a canonical `id` property; for composite keys the loader builds IDs like `salesOrder|salesOrderItem` or `companyCode|fiscalYear|accountingDocument|accountingDocumentItem`.

**Relationships (examples):**

- `(:BusinessPartner)-[:PLACED]->(:SalesOrder)`
- `(:BusinessPartner)-[:BILLED]->(:BillingDocument)`
- `(:SalesOrder)-[:DELIVERED_IN]->(:Delivery)`
- `(:BillingDocument)-[:SETTLES]<-(:Payment)`
- `(:SalesOrder)-[:HAS_ITEM]->(:SalesOrderItem)`
- `(:SalesOrderItem)-[:OF_PRODUCT]->(:Product)`
- `(:SalesOrderItem)-[:HAS_SCHEDULE_LINE]->(:SalesOrderScheduleLine)`
- `(:BillingDocument)-[:HAS_ITEM]->(:BillingItem)`
- `(:BillingItem)-[:OF_PRODUCT]->(:Product)`
- `(:BusinessPartner)-[:HAS_COMPANY_ASSIGNMENT]->(:CustomerCompany)`
- `(:BusinessPartner)-[:HAS_SALES_AREA_ASSIGNMENT]->(:CustomerSalesArea)`
- `(:BusinessPartner)-[:HAS_ADDRESS]->(:BusinessPartnerAddress)`
- `(:Product)-[:HAS_DESCRIPTION]->(:ProductDescription)`
- `(:Product)-[:HAS_PLANT]->(:ProductPlant)-[:IN_PLANT]->(:Plant)`
- `(:Product)-[:HAS_STORAGE_LOCATION]->(:ProductStorageLocation)-[:IN_PLANT]->(:Plant)`
- `(:BusinessPartner)-[:HAS_AR_ITEM]->(:ARItem)`
- `(:BillingDocument)-[:AR_FOR_INVOICE]->(:ARItem)`

These are all configured in `NODE_DATASETS` and `RELATION_DATASETS` inside the loader.

### 4.2 How transformation works

In the loader:

- `_prepare_record` builds composite IDs and flattens nested time fields.
- `_sanitize_value` converts all values into types that Neo4j accepts as properties.
- Nodes are merged with `MERGE (n:Label {id: row.id}) SET n += row`.
- Relationships are merged with `MERGE (a)-[r:TYPE]->(b)` using the `id` fields.

### 4.3 Run the loader

From the project root (where `data/` and `neo4j_pipeline/` live):

```bash
python neo4j_pipeline/load_jsonl_to_neo4j.py
```

The script will:

1. Load all configured node datasets under `data/`.
2. Load all configured relationship datasets, wiring headers, items, products, AR, and payments into a single connected graph.

---

## 5. LLM QA over the graph (LangChain + Groq)

The file [neo4j_pipeline/graph_qa.py](neo4j_pipeline/graph_qa.py) implements a **custom NL → Cypher → Neo4j → answer** pipeline.

### 5.1 How it works

- Uses `Neo4jGraph` (from `langchain_neo4j`) to introspect the current schema.
- Uses `ChatGroq` with a Groq‑hosted model (`llama-3.3-70b-versatile`).
- A detailed system prompt (`SYSTEM_SCHEMA_PROMPT`) describes the business graph and recommended traversal patterns.
- `_build_cypher_generator` asks the LLM to output only a ```cypher``` block.
- Several post‑processing helpers clean the Cypher:
  - `_extract_cypher`, `_dedupe_return_clause`, `_fix_payment_path_conflict`, `_fix_optional_relationship_markers`, `_fix_payment_alias_conflicts`.
- The Cypher is executed via `Neo4jGraph.query`.
- `_summarize_results` uses the LLM to convert raw rows into a concise business answer.

Public entry point:

- `answer_question(question: str) -> str`

### 5.2 Running QA from CLI

Examples:

```bash
python neo4j_pipeline/graph_qa.py "Show the full lifecycle of sales order 740506 from order to payment"

python neo4j_pipeline/graph_qa.py
```

In interactive mode it will prompt: “Enter your question about orders, deliveries, invoices, or payments”.

---

## 6. FastAPI backend (chat + graph APIs)

The backend in [neo4j_pipeline/app.py](neo4j_pipeline/app.py) wires the loader/QA into HTTP endpoints.

### 6.1 Endpoints

- `POST /api/chat` and `GET /api/chat`
  - Body / query: `{ "question": "..." }`.
  - Validates that the question is non‑empty and **in domain** (orders, deliveries, invoices, payments, customers, products, addresses).
  - If out of domain, returns a fixed guardrail message.
  - Otherwise calls `answer_question` and returns `{ "answer": "..." }`.

- `POST /api/graph`
  - Body: `{ "id": "<node id>", "label": "OptionalLabel" }`.
  - Looks up the center node by `id` (and label if provided) and returns its neighborhood up to a limit:
    - `center`: the center node.
    - `nodes`: surrounding nodes with `id`, `label`, and `properties`.
    - `edges`: relationships between them.

- `GET /api/full-graph`
  - Returns a **capped** full‑graph snapshot: up to ~2000 relationships.
  - Used by the UI to render an initial view.

- Static + root:
  - Mounts `/static` to serve the frontend.
  - `/` serves `static/index.html` when available.

### 6.2 Run the API server

From the project root:

```bash
uvicorn neo4j_pipeline.app:app --reload
```

This starts FastAPI at `http://localhost:8000`.

---

## 7. Web UI – graph visualization + chat

The UI lives in [static/index.html](static/index.html) and uses **Cytoscape.js** for graph rendering.

### 7.1 Features

- **Graph view** (left side):
  - Loads a capped full graph via `/api/full-graph` on page load and runs a single layout.
  - Nodes are shown as **orange dots**, edges as **blue lines** (no text labels on the graph itself).
  - Clicking a node expands its neighborhood via `/api/graph` and shows its properties in an info panel.
  - Focus/highlight on the selected node with smooth zoom/center.

- **Chat panel** (right side):
  - Sends questions to `/api/chat`.
  - Shows user and model messages.
  - If the question contains a numeric ID (e.g. sales order number), the UI automatically loads that node’s neighborhood and focuses it in the graph.
  - Press **Enter** to send, **Shift+Enter** for a newline; empty messages are ignored and the input clears after sending.
  - Handles errors from the backend gracefully (shows error text instead of `undefined`).

- **Legend + node info**:
  - Small legend explaining orange (entities) and blue (relationships).
  - A floating info box shows the selected node’s properties, with implementation details like `Node`/`tuple` filtered out.

### 7.2 Open the UI

Once the FastAPI server is running:

- Go to `http://localhost:8000/` (root) – it serves the UI.
  - Alternatively, `http://localhost:8000/static/index.html`.

---

## 8. End‑to‑end workflow

1. **Prepare data** under `data/` (JSONL files in the expected folders).
2. **Configure environment** (`NEO4J_*`, `GROQ_API_KEY`, `.env` if desired).
3. **Load graph** into Neo4j:
   - `python neo4j_pipeline/load_jsonl_to_neo4j.py`
4. **Start API + UI**:
   - `uvicorn neo4j_pipeline.app:app --reload`
5. **Explore + ask questions**:
   - Open the browser UI, click nodes to explore flows, or ask questions in chat like:
     - "Identify sales orders that have broken or incomplete flows (delivered but not billed, billed without delivery)."
     - "For customer 1000001, summarize open AR items and related invoices." 

From here you can customize:

- The graph model (`NODE_DATASETS`, `RELATION_DATASETS`).
- The LLM prompt and post‑processing logic in `graph_qa.py`.
- The UI behavior and styling in `static/index.html`.

This README reflects the current full project (loader, LLM QA, FastAPI API, and Cytoscape UI) so it serves as the main guide to running and extending Dodge AI.