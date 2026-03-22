import os
import re
import sys
from typing import Any, Dict, List

from langchain_neo4j import Neo4jGraph
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from dotenv import load_dotenv
load_dotenv()

SYSTEM_SCHEMA_PROMPT = """
You are an expert business operations analyst who writes Cypher queries for a Neo4j graph.

GRAPH SCHEMA (high level):
- Core header nodes:
    - (c:BusinessPartner (id, businessPartnerFullName, businessPartnerCategory, ...))
    - (o:SalesOrder (id, salesOrderType, salesOrganization, requestedDeliveryDate, transactionCurrency, totalNetAmount, ...))
    - (d:Delivery (id, actualGoodsMovementDate, shippingPoint, ...))
    - (b:BillingDocument (id, billingDocumentType, billingDocumentDate, totalNetAmount, transactionCurrency, companyCode, fiscalYear, accountingDocument, billingDocumentIsCancelled, ...))
    - (p:Payment (id, companyCode, fiscalYear, amountInTransactionCurrency, transactionCurrency, customer, invoiceReference, postingDate, ...))

- Item / schedule nodes:
    - (:SalesOrderItem (id = salesOrderItemId, salesOrder, salesOrderItem, material, requestedQuantity, netAmount, productionPlant, storageLocation, ...))
    - (:SalesOrderScheduleLine (id = salesOrderScheduleLineId, salesOrder, salesOrderItem, scheduleLine, confirmedDeliveryDate, confdOrderQtyByMatlAvailCheck, ...))
    - (:BillingItem (id = billingDocumentItemId, billingDocument, billingDocumentItem, material, billingQuantity, netAmount, ...))

- Product / plant / storage nodes:
    - (:Product (id = product, productType, baseUnit, productGroup, division, industrySector, ...))
    - (:ProductDescription (id = productDescriptionId, product, language, productDescription))
    - (:Plant (id = plant, plantName, valuationArea, salesOrganization, distributionChannel, division, ...))
    - (:ProductPlant (id = productPlantId, product, plant, countryOfOrigin, profitCenter, ...))
    - (:ProductStorageLocation (id = productStorageLocationId, product, plant, storageLocation, ...))

- AR / accounting nodes:
    - (:ARItem (id = journalEntryItemId, companyCode, fiscalYear, accountingDocument, accountingDocumentItem, transactionCurrency, amountInTransactionCurrency, companyCodeCurrency, amountInCompanyCodeCurrency, customer, clearingDate, clearingAccountingDocument, ...))

- Customer master detail nodes:
    - (:CustomerCompany (id = customerCompanyId, customer, companyCode, reconciliationAccount, paymentTerms, paymentMethodsList, ...))
    - (:CustomerSalesArea (id = customerSalesAreaId, customer, salesOrganization, distributionChannel, division, currency, incotermsClassification, customerPaymentTerms, ...))
    - (:BusinessPartnerAddress (id = businessPartnerAddressId, businessPartner, addressId, cityName, country, postalCode, streetName, ...))

- Relationships:
  - (c:BusinessPartner)-[:PLACED]->(o:SalesOrder)
  - (c:BusinessPartner)-[:BILLED]->(b:BillingDocument)
  - (o:SalesOrder)-[:DELIVERED_IN]->(d:Delivery)
  - (b1:BillingDocument)-[:CANCELS]->(b2:BillingDocument)
  - (p:Payment)-[:SETTLES]->(b:BillingDocument)
  - (o:SalesOrder)-[:HAS_ITEM]->(:SalesOrderItem)
  - (:SalesOrderItem)-[:OF_PRODUCT]->(:Product)
  - (:SalesOrderItem)-[:HAS_SCHEDULE_LINE]->(:SalesOrderScheduleLine)
  - (b:BillingDocument)-[:HAS_ITEM]->(:BillingItem)
  - (:BillingItem)-[:OF_PRODUCT]->(:Product)
  - (c:BusinessPartner)-[:HAS_COMPANY_ASSIGNMENT]->(:CustomerCompany)
  - (c:BusinessPartner)-[:HAS_SALES_AREA_ASSIGNMENT]->(:CustomerSalesArea)
  - (c:BusinessPartner)-[:HAS_ADDRESS]->(:BusinessPartnerAddress)
  - (:Product)-[:HAS_DESCRIPTION]->(:ProductDescription)
  - (:Product)-[:HAS_PLANT]->(:ProductPlant)
  - (:ProductPlant)-[:IN_PLANT]->(:Plant)
  - (:Product)-[:HAS_STORAGE_LOCATION]->(:ProductStorageLocation)
  - (:ProductStorageLocation)-[:IN_PLANT]->(:Plant)
  - (c:BusinessPartner)-[:HAS_AR_ITEM]->(:ARItem)
  - (b:BillingDocument)-[:AR_FOR_INVOICE]->(:ARItem)

INSTRUCTIONS:
- Always use the existing schema (labels, relationship types, and id property) when generating Cypher.
- Prefer matching by ids when the user gives explicit order numbers, delivery numbers, invoice numbers, or payment/accounting document numbers.
- For customer-centric questions, traverse from BusinessPartner to the other nodes via PLACED, BILLED, HAS_AR_ITEM, SETTLES.
- For order/item/product questions, traverse via HAS_ITEM, OF_PRODUCT, HAS_SCHEDULE_LINE, HAS_PLANT, HAS_STORAGE_LOCATION.
- For lifecycle questions, follow the path:
    (c:BusinessPartner)-[:PLACED]->(o:SalesOrder)-[:HAS_ITEM]->(oi:SalesOrderItem)-[:OF_PRODUCT]->(pr:Product)
    (oi)-[:HAS_SCHEDULE_LINE]->(sl:SalesOrderScheduleLine)
    (o)-[:DELIVERED_IN]->(d:Delivery)
    OPTIONAL MATCH (o)-[:BILLED]->(b:BillingDocument)-[:HAS_ITEM]->(bi:BillingItem)-[:OF_PRODUCT]->(pr)
    (b)<-[:SETTLES]-(p:Payment)
    (b)-[:AR_FOR_INVOICE]->(:ARItem)
- Always add a reasonable LIMIT (e.g. LIMIT 50) to queries that could return many rows.
- Only return fields that are necessary to answer the question clearly.

Additional constraints when writing Cypher:
- Do NOT use path variables like `MATCH p = ...`. Always match nodes directly, e.g. `MATCH (c:BusinessPartner)-[:PLACED]->(o:SalesOrder)`.
- Use `p` only as the Payment node variable `(p:Payment)` and not for paths.

When I ask you a question, you must respond ONLY with a Cypher query, nothing else.
Wrap the Cypher in a Markdown code block like:
```cypher
MATCH ...
RETURN ...
```
"""


def get_neo4j_graph() -> Neo4jGraph:
    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    return Neo4jGraph(url=uri, username=user, password=password)


def get_llm() -> ChatGroq:
    # Requires GROQ_API_KEY in the environment
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0.1,
    )


def _build_cypher_generator():
    """LLM chain that turns NL questions into Cypher using the schema string."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_SCHEMA_PROMPT),
            (
                "user",
                "Question: {question}\n\nRemember: respond with Cypher only, in a ```cypher``` block.",
            ),
        ]
    )
    llm = get_llm()
    return prompt | llm | StrOutputParser()


def _extract_cypher(text: str) -> str:
    """Extract Cypher code from a ```cypher``` block or return raw text."""

    lower = text.lower()
    start = lower.find("```cypher")
    if start != -1:
        start = text.find("\n", start)
        end = text.find("```", start + 1)
        if end != -1:
            return text[start + 1 : end].strip()
    return text.strip()


def _dedupe_return_clause(cypher: str) -> str:
    """Remove duplicate columns in the last RETURN line of the query.

    Guards against LLM-generated queries like:
      RETURN p, c, o, d, b, p
    which cause Neo4j to error with "Multiple result columns with the same name".
    """

    lines = cypher.splitlines()
    last_return_idx = -1
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.upper().startswith("RETURN "):
            last_return_idx = i

    if last_return_idx == -1:
        return cypher

    line = lines[last_return_idx]
    leading_ws_len = len(line) - len(line.lstrip())
    indent = line[:leading_ws_len]
    stripped = line.lstrip()
    return_expr = stripped[len("RETURN ") :].strip()

    # If the RETURN clause already uses aliases ("AS"), leave it as-is
    if " AS " in return_expr.upper():
        return cypher

    seen = set()
    cols: List[str] = []
    for raw_col in return_expr.split(","):
        col = raw_col.strip()
        if not col:
            continue
        if col in seen:
            continue
        seen.add(col)
        cols.append(col)

    new_line = indent + "RETURN " + ", ".join(cols)
    lines[last_return_idx] = new_line
    return "\n".join(lines)


def _fix_payment_path_conflict(cypher: str) -> str:
    """Avoid using `p` as both a path and Payment node variable.

    If the LLM creates a path like `MATCH p = ...` and later uses `p:Payment`,
    Neo4j raises a type mismatch. When we detect `MATCH p =`, we rename the
    Payment node variable from `p` to `pay` in MATCH/OPTIONAL MATCH and RETURN.
    """

    if not re.search(r"(?i)\bMATCH\s+p\s*=", cypher):
        return cypher

    # Rename Payment node pattern and property uses
    cypher = re.sub(r"\(p:Payment\)", "(pay:Payment)", cypher)
    cypher = re.sub(r"\bp\.", "pay.", cypher)

    # Adjust bare `p` references in RETURN lines
    lines = cypher.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.upper().startswith("RETURN "):
            lines[i] = re.sub(r"\bp\b", "pay", line)
    return "\n".join(lines)


def _fix_optional_relationship_markers(cypher: str) -> str:
    """Replace invalid relationship types like [:BILLED?] with [:BILLED]."""

    return re.sub(r"\[:([A-Za-z0-9_]+)\?\]", r"[:\1]", cypher)


def _fix_payment_alias_conflicts(cypher: str) -> str:
    """Ensure `p` is not reused for both Product and Payment.

    Sometimes the LLM generates patterns like:
      OPTIONAL MATCH (soi)-[:OF_PRODUCT]->(p:Product)
      ...
      OPTIONAL MATCH (b)<-[:SETTLES]-(p:Payment)

    This reuses `p` for two different node labels in the same query and
    also causes the RETURN clause to accidentally return product ids
    where payment ids are expected. To avoid this, we rename the
    Payment variable from `p` to `pay` and update subsequent usages.
    """

    lines = cypher.splitlines()
    payment_line_idx = None

    for i, line in enumerate(lines):
        if re.search(r"\(p\s*:\s*Payment\)", line):
            # Rename the Payment variable on this line
            lines[i] = re.sub(r"\(p\s*:\s*Payment\)", "(pay:Payment)", line)
            payment_line_idx = i
            break

    if payment_line_idx is None:
        return cypher

    # For all lines after the Payment MATCH, rewrite p.* to pay.*
    for j in range(payment_line_idx + 1, len(lines)):
        lines[j] = re.sub(r"\bp\.", "pay.", lines[j])

    return "\n".join(lines)


def _fix_top_level_case_expressions(cypher: str) -> str:
    """Comment out bare top-level CASE blocks that break Cypher.

    The LLM sometimes produces standalone CASE blocks like:

        MATCH ...
        OPTIONAL MATCH ...
        CASE WHEN d IS NOT NULL AND b IS NULL THEN 'Delivered but not billed'
             WHEN ... THEN ...
        END AS flowStatus
        RETURN ...

    In Cypher, CASE must be an expression inside RETURN/WITH, not its
    own statement. Rather than trying to perfectly rewrite these, we
    simply comment out the whole CASE...END block so the query remains
    valid and the summarizer can still infer statuses from raw data.
    """

    lines = cypher.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if not stripped:
            i += 1
            continue

        upper = stripped.upper()
        if not upper.startswith("CASE "):
            i += 1
            continue

        # Found the start of a CASE block; search for END ... AS ...
        end_idx = i
        for j in range(i, len(lines)):
            s = lines[j].lstrip().upper()
            if "END" in s and " AS " in s:
                end_idx = j
                break

        # Comment out the CASE block lines
        for k in range(i, end_idx + 1):
            if lines[k].lstrip():
                lines[k] = "// " + lines[k]

        i = end_idx + 1

    return "\n".join(lines)


def _summarize_results(question: str, cypher: str, rows: List[Dict[str, Any]]) -> str:
    """Use the LLM to turn raw Cypher results into a natural-language answer."""

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a senior business analyst. Given a question, the Cypher "
                "used to query Neo4j, and the JSON results, write a concise answer.",
            ),
            (
                "user",
                "Question: {question}\n\nCypher: {cypher}\n\nResults (JSON):\n{results}",
            ),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"question": question, "cypher": cypher, "results": rows})


def _answer_broken_or_incomplete_flows(graph: Neo4jGraph) -> str:
    """Domain-specific handler for 'broken or incomplete flows' questions.

    Computes, for each SalesOrder, whether it has delivery and/or billing,
    and flags those whose lifecycle is incomplete.
    """

    cypher = """
    MATCH (o:SalesOrder)
    OPTIONAL MATCH (o)-[:DELIVERED_IN]->(d:Delivery)
    OPTIONAL MATCH (o)-[:BILLED]->(b:BillingDocument)
    WITH o.id AS orderId,
         (COUNT(DISTINCT d) > 0) AS hasDelivery,
         (COUNT(DISTINCT b) > 0) AS hasBilling
    WITH orderId, hasDelivery, hasBilling,
         CASE
           WHEN hasDelivery AND NOT hasBilling THEN 'Delivered but not billed'
           WHEN NOT hasDelivery AND hasBilling THEN 'Billed without delivery'
           WHEN NOT hasDelivery AND NOT hasBilling THEN 'Neither delivered nor billed'
           ELSE 'Complete flow'
         END AS flowStatus
    RETURN orderId, flowStatus
    ORDER BY orderId
    LIMIT 100
    """

    rows: List[Dict[str, Any]] = graph.query(cypher)
    broken = [r for r in rows if r.get("flowStatus") != "Complete flow"]

    if not broken:
        return (
            "All sampled sales orders (up to 100) have a complete flow "
            "from delivery to billing, based on the current data."
        )

    lines = [
        "Sales orders with broken or incomplete flows (up to 100 orders checked):"
    ]
    for r in broken:
        lines.append(f"- Order {r.get('orderId')}: {r.get('flowStatus')}")

    return "\n".join(lines)


def answer_question(question: str) -> str:
    graph = get_neo4j_graph()

    # Special-case certain domain questions where we have a robust
    # hand-written Cypher query that is less error-prone than the LLM.
    q_lower = question.lower()
    if "broken or incomplete flows" in q_lower:
        return _answer_broken_or_incomplete_flows(graph)

    # Step 1: generate Cypher from the question and current schema
    cypher_gen = _build_cypher_generator()
    cypher_raw = cypher_gen.invoke({"question": question})
    cypher = _extract_cypher(cypher_raw)
    cypher = _dedupe_return_clause(cypher)
    cypher = _fix_payment_path_conflict(cypher)
    cypher = _fix_optional_relationship_markers(cypher)
    cypher = _fix_payment_alias_conflicts(cypher)
    cypher = _fix_top_level_case_expressions(cypher)

    # Step 2: run Cypher against Neo4j via langchain_neo4j.Neo4jGraph
    rows: List[Dict[str, Any]] = graph.query(cypher)

    # Step 3: summarize results back to the user
    return _summarize_results(question, cypher, rows)


def main() -> None:
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = input("Enter your question about orders, deliveries, invoices, or payments: ")

    if not question.strip():
        print("No question provided.")
        sys.exit(1)

    try:
        answer = answer_question(question)
        print("\nAnswer:\n" + str(answer))
    except Exception as exc:
        print(f"Error while querying graph: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
