import glob
import json
import os
from typing import Any, Dict, List

from neo4j import GraphDatabase

from dotenv import load_dotenv

load_dotenv()

BATCH_SIZE = 1000


NODE_DATASETS: Dict[str, Dict[str, Any]] = {
    "business_partners": {
        "glob": os.path.join("data", "business_partners", "*.jsonl"),
        "label": "BusinessPartner",
        "id_field": "businessPartner",
    },
    "business_partner_addresses": {
        "glob": os.path.join("data", "business_partner_addresses", "*.jsonl"),
        "label": "BusinessPartnerAddress",
        "id_field": "businessPartnerAddressId",
        "composite_id_fields": ["businessPartner", "addressId"],
    },
    "customer_company_assignments": {
        "glob": os.path.join("data", "customer_company_assignments", "*.jsonl"),
        "label": "CustomerCompany",
        "id_field": "customerCompanyId",
        "composite_id_fields": ["customer", "companyCode"],
    },
    "customer_sales_area_assignments": {
        "glob": os.path.join("data", "customer_sales_area_assignments", "*.jsonl"),
        "label": "CustomerSalesArea",
        "id_field": "customerSalesAreaId",
        "composite_id_fields": [
            "customer",
            "salesOrganization",
            "distributionChannel",
            "division",
        ],
    },
    "products": {
        "glob": os.path.join("data", "products", "*.jsonl"),
        "label": "Product",
        "id_field": "product",
    },
    "product_descriptions": {
        "glob": os.path.join("data", "product_descriptions", "*.jsonl"),
        "label": "ProductDescription",
        "id_field": "productDescriptionId",
        "composite_id_fields": ["product", "language"],
    },
    "plants": {
        "glob": os.path.join("data", "plants", "*.jsonl"),
        "label": "Plant",
        "id_field": "plant",
    },
    "product_plants": {
        "glob": os.path.join("data", "product_plants", "*.jsonl"),
        "label": "ProductPlant",
        "id_field": "productPlantId",
        "composite_id_fields": ["product", "plant"],
    },
    "product_storage_locations": {
        "glob": os.path.join("data", "product_storage_locations", "*.jsonl"),
        "label": "ProductStorageLocation",
        "id_field": "productStorageLocationId",
        "composite_id_fields": ["product", "plant", "storageLocation"],
    },
    "sales_order_headers": {
        "glob": os.path.join("data", "sales_order_headers", "*.jsonl"),
        "label": "SalesOrder",
        "id_field": "salesOrder",
    },
    "sales_order_items": {
        "glob": os.path.join("data", "sales_order_items", "*.jsonl"),
        "label": "SalesOrderItem",
        "id_field": "salesOrderItemId",
        "composite_id_fields": ["salesOrder", "salesOrderItem"],
    },
    "sales_order_schedule_lines": {
        "glob": os.path.join("data", "sales_order_schedule_lines", "*.jsonl"),
        "label": "SalesOrderScheduleLine",
        "id_field": "salesOrderScheduleLineId",
        "composite_id_fields": ["salesOrder", "salesOrderItem", "scheduleLine"],
    },
    "outbound_delivery_headers": {
        "glob": os.path.join("data", "outbound_delivery_headers", "*.jsonl"),
        "label": "Delivery",
        "id_field": "deliveryDocument",
    },
    "billing_document_headers": {
        "glob": os.path.join("data", "billing_document_headers", "*.jsonl"),
        "label": "BillingDocument",
        "id_field": "billingDocument",
    },
    "billing_document_items": {
        "glob": os.path.join("data", "billing_document_items", "*.jsonl"),
        "label": "BillingItem",
        "id_field": "billingDocumentItemId",
        "composite_id_fields": ["billingDocument", "billingDocumentItem"],
    },
    "payments_accounts_receivable": {
        "glob": os.path.join("data", "payments_accounts_receivable", "*.jsonl"),
        "label": "Payment",
        # use accountingDocument as a simple payment identifier for this sample
        "id_field": "accountingDocument",
    },
    "journal_entry_items_accounts_receivable": {
        "glob": os.path.join(
            "data", "journal_entry_items_accounts_receivable", "*.jsonl"
        ),
        "label": "ARItem",
        "id_field": "journalEntryItemId",
        "composite_id_fields": [
            "companyCode",
            "fiscalYear",
            "accountingDocument",
            "accountingDocumentItem",
        ],
    },
}


RELATION_DATASETS: List[Dict[str, Any]] = [
    {
        "name": "CUSTOMER_PLACED_ORDER",
        "dataset": "sales_order_headers",
        "source_glob": os.path.join("data", "sales_order_headers", "*.jsonl"),
        "type": "PLACED",
        "from_label": "BusinessPartner",
        "to_label": "SalesOrder",
        # sales_order_headers.soldToParty -> business_partners.id (customer)
        "from_key_in_row": "soldToParty",
        # sales_order_headers.salesOrder -> sales order header primary key
        "to_key_in_row": "salesOrder",
    },
    {
        "name": "CUSTOMER_COMPANY_ASSIGNMENT",
        "dataset": "customer_company_assignments",
        "source_glob": os.path.join("data", "customer_company_assignments", "*.jsonl"),
        "type": "HAS_COMPANY_ASSIGNMENT",
        "from_label": "BusinessPartner",
        "to_label": "CustomerCompany",
        # customer_company_assignments.customer -> business_partners.businessPartner
        "from_key_in_row": "customer",
        # composite node id for the assignment
        "to_key_in_row": "customerCompanyId",
    },
    {
        "name": "CUSTOMER_SALES_AREA_ASSIGNMENT",
        "dataset": "customer_sales_area_assignments",
        "source_glob": os.path.join(
            "data", "customer_sales_area_assignments", "*.jsonl"
        ),
        "type": "HAS_SALES_AREA_ASSIGNMENT",
        "from_label": "BusinessPartner",
        "to_label": "CustomerSalesArea",
        # customer_sales_area_assignments.customer -> business_partners.businessPartner
        "from_key_in_row": "customer",
        "to_key_in_row": "customerSalesAreaId",
    },
    {
        "name": "CUSTOMER_BILLED_INVOICE",
        "dataset": "billing_document_headers",
        "source_glob": os.path.join("data", "billing_document_headers", "*.jsonl"),
        "type": "BILLED",
        "from_label": "BusinessPartner",
        "to_label": "BillingDocument",
        # billing_document_headers.soldToParty -> business_partners.id (customer)
        "from_key_in_row": "soldToParty",
        # billing_document_headers.billingDocument -> billing document primary key
        "to_key_in_row": "billingDocument",
    },
    {
        "name": "CUSTOMER_ADDRESSES",
        "dataset": "business_partner_addresses",
        "source_glob": os.path.join("data", "business_partner_addresses", "*.jsonl"),
        "type": "HAS_ADDRESS",
        "from_label": "BusinessPartner",
        "to_label": "BusinessPartnerAddress",
        # business_partner_addresses.businessPartner -> business_partners.businessPartner
        "from_key_in_row": "businessPartner",
        "to_key_in_row": "businessPartnerAddressId",
    },
    {
        "name": "ORDER_HAS_ITEM",
        "dataset": "sales_order_items",
        "source_glob": os.path.join("data", "sales_order_items", "*.jsonl"),
        "type": "HAS_ITEM",
        "from_label": "SalesOrder",
        "to_label": "SalesOrderItem",
        # sales_order_items.salesOrder -> sales_order_headers.salesOrder
        "from_key_in_row": "salesOrder",
        # composite id for the item (built by _prepare_record)
        "to_key_in_row": "salesOrderItemId",
    },
    {
        "name": "ORDER_ITEM_MATERIAL",
        "dataset": "sales_order_items",
        "source_glob": os.path.join("data", "sales_order_items", "*.jsonl"),
        "type": "OF_PRODUCT",
        "from_label": "SalesOrderItem",
        "to_label": "Product",
        # composite id for the item (built by _prepare_record)
        "from_key_in_row": "salesOrderItemId",
        # sales_order_items.material -> products.product
        "to_key_in_row": "material",
    },
    {
        "name": "ORDER_ITEM_SCHEDULE_LINE",
        "dataset": "sales_order_schedule_lines",
        "source_glob": os.path.join(
            "data", "sales_order_schedule_lines", "*.jsonl"
        ),
        "type": "HAS_SCHEDULE_LINE",
        "from_label": "SalesOrderItem",
        "to_label": "SalesOrderScheduleLine",
        # derived composite id for the item on schedule line records (built by _prepare_record)
        "from_key_in_row": "salesOrderItemId",
        "to_key_in_row": "salesOrderScheduleLineId",
    },
    {
        "name": "ORDER_DELIVERED_IN",
        "dataset": "outbound_delivery_items",
        # link sales orders to deliveries using outbound_delivery_items
        "source_glob": os.path.join("data", "outbound_delivery_items", "*.jsonl"),
        "type": "DELIVERED_IN",
        "from_label": "SalesOrder",
        "to_label": "Delivery",
        # outbound_delivery_items.referenceSdDocument -> sales_order_headers.salesOrder
        "from_key_in_row": "referenceSdDocument",
        # outbound_delivery_items.deliveryDocument -> outbound_delivery_headers.deliveryDocument
        "to_key_in_row": "deliveryDocument",
    },
    {
        "name": "BILLING_DOCUMENT_CANCELLATION",
        "dataset": "billing_document_headers",
        "source_glob": os.path.join("data", "billing_document_headers", "*.jsonl"),
        # a cancelling billing document CANCELS another billing document
        "type": "CANCELS",
        "from_label": "BillingDocument",
        "to_label": "BillingDocument",
        # current document id
        "from_key_in_row": "billingDocument",
        # id of the cancelled billing document (may be empty)
        "to_key_in_row": "cancelledBillingDocument",
    },
    {
        "name": "BILLING_HAS_ITEM",
        "dataset": "billing_document_items",
        "source_glob": os.path.join("data", "billing_document_items", "*.jsonl"),
        "type": "HAS_ITEM",
        "from_label": "BillingDocument",
        "to_label": "BillingItem",
        # billing_document_items.billingDocument -> billing_document_headers.billingDocument
        "from_key_in_row": "billingDocument",
        # composite id for billing item (built by _prepare_record)
        "to_key_in_row": "billingDocumentItemId",
    },
    {
        "name": "BILLING_ITEM_MATERIAL",
        "dataset": "billing_document_items",
        "source_glob": os.path.join("data", "billing_document_items", "*.jsonl"),
        "type": "OF_PRODUCT",
        "from_label": "BillingItem",
        "to_label": "Product",
        # composite id for billing item (built by _prepare_record)
        "from_key_in_row": "billingDocumentItemId",
        # billing_document_items.material -> products.product
        "to_key_in_row": "material",
    },
    {
        "name": "PAYMENT_SETTLES_INVOICE",
        "dataset": "payments_accounts_receivable",
        "source_glob": os.path.join("data", "payments_accounts_receivable", "*.jsonl"),
        "type": "SETTLES",
        "from_label": "Payment",
        "to_label": "BillingDocument",
        # payments_accounts_receivable.accountingDocument -> payments_accounts_receivable primary key
        "from_key_in_row": "accountingDocument",
        # payments_accounts_receivable.invoiceReference -> billing_document_headers.billingDocument
        "to_key_in_row": "invoiceReference",
    },
    {
        "name": "ARITEM_FOR_CUSTOMER",
        "dataset": "journal_entry_items_accounts_receivable",
        "source_glob": os.path.join(
            "data", "journal_entry_items_accounts_receivable", "*.jsonl"
        ),
        "type": "HAS_AR_ITEM",
        "from_label": "BusinessPartner",
        "to_label": "ARItem",
        # journal_entry_items_accounts_receivable.customer -> business_partners.businessPartner
        "from_key_in_row": "customer",
        # composite id for AR item (built by _prepare_record)
        "to_key_in_row": "journalEntryItemId",
    },
    {
        "name": "ARITEM_FOR_BILLING_DOCUMENT",
        "dataset": "journal_entry_items_accounts_receivable",
        "source_glob": os.path.join(
            "data", "journal_entry_items_accounts_receivable", "*.jsonl"
        ),
        "type": "AR_FOR_INVOICE",
        "from_label": "BillingDocument",
        "to_label": "ARItem",
        # journal_entry_items_accounts_receivable.invoiceReference -> billing_document_headers.billingDocument
        "from_key_in_row": "invoiceReference",
        "to_key_in_row": "journalEntryItemId",
    },
    {
        "name": "PRODUCT_HAS_DESCRIPTION",
        "dataset": "product_descriptions",
        "source_glob": os.path.join("data", "product_descriptions", "*.jsonl"),
        "type": "HAS_DESCRIPTION",
        "from_label": "Product",
        "to_label": "ProductDescription",
        # product_descriptions.product -> products.product
        "from_key_in_row": "product",
        # composite id for description (built by _prepare_record)
        "to_key_in_row": "productDescriptionId",
    },
    {
        "name": "PRODUCT_HAS_PLANT",
        "dataset": "product_plants",
        "source_glob": os.path.join("data", "product_plants", "*.jsonl"),
        "type": "HAS_PLANT",
        "from_label": "Product",
        "to_label": "ProductPlant",
        # product_plants.product -> products.product
        "from_key_in_row": "product",
        # composite id for product-plant (built by _prepare_record)
        "to_key_in_row": "productPlantId",
    },
    {
        "name": "PRODUCT_PLANT_IN_PLANT",
        "dataset": "product_plants",
        "source_glob": os.path.join("data", "product_plants", "*.jsonl"),
        "type": "IN_PLANT",
        "from_label": "ProductPlant",
        "to_label": "Plant",
        # composite id for product-plant (built by _prepare_record)
        "from_key_in_row": "productPlantId",
        # product_plants.plant -> plants.plant
        "to_key_in_row": "plant",
    },
    {
        "name": "PRODUCT_HAS_STORAGE_LOCATION",
        "dataset": "product_storage_locations",
        "source_glob": os.path.join(
            "data", "product_storage_locations", "*.jsonl"
        ),
        "type": "HAS_STORAGE_LOCATION",
        "from_label": "Product",
        "to_label": "ProductStorageLocation",
        # product_storage_locations.product -> products.product
        "from_key_in_row": "product",
        # composite id for product-plant-storageLocation (built by _prepare_record)
        "to_key_in_row": "productStorageLocationId",
    },
    {
        "name": "PRODUCT_STORAGE_LOCATION_IN_PLANT",
        "dataset": "product_storage_locations",
        "source_glob": os.path.join(
            "data", "product_storage_locations", "*.jsonl"
        ),
        "type": "IN_PLANT",
        "from_label": "ProductStorageLocation",
        "to_label": "Plant",
        # composite id for product-plant-storageLocation (built by _prepare_record)
        "from_key_in_row": "productStorageLocationId",
        # product_storage_locations.plant -> plants.plant
        "to_key_in_row": "plant",
    },
]


def get_driver() -> GraphDatabase.driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "password")
    return GraphDatabase.driver(uri, auth=(user, password))


def _sanitize_value(value: Any) -> Any:
    """Convert JSON values into types allowed as Neo4j properties.

    Neo4j node properties must be primitives (str, int, float, bool, None)
    or lists of primitives. Any nested objects (e.g. time maps
    like {"hours": 13, "minutes": 36, "seconds": 43}) are converted
    to JSON strings so they can still be inspected if needed.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        sanitized_list = []
        for item in value:
            if item is None or isinstance(item, (str, int, float, bool)):
                sanitized_list.append(item)
            else:
                sanitized_list.append(json.dumps(item, ensure_ascii=False))
        return sanitized_list

    # For dicts or any other complex/nested structures, store as JSON string
    return json.dumps(value, ensure_ascii=False)


def _prepare_record(dataset: str, cfg: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """Apply dataset-specific transformations before sanitization.

    - Build composite ids when `composite_id_fields` is configured.
    - Flatten creationTime maps into primitive hour/minute/second fields.
    - Add helper ids (e.g. salesOrderItemId on schedule lines) used for relations.
    """

    # Flatten creationTime like {"hours": 13, "minutes": 36, "seconds": 43}
    if "creationTime" in record and isinstance(record["creationTime"], dict):
        ct = record["creationTime"]
        record["creationTime_hours"] = ct.get("hours")
        record["creationTime_minutes"] = ct.get("minutes")
        record["creationTime_seconds"] = ct.get("seconds")
        # Drop the nested map to avoid invalid property types
        del record["creationTime"]

    # Composite primary key for this dataset
    id_field = cfg.get("id_field")
    composite_fields = cfg.get("composite_id_fields")
    if id_field and composite_fields and id_field not in record:
        try:
            composite_parts = [str(record[f]) for f in composite_fields]
            record[id_field] = "|".join(composite_parts)
        except KeyError:
            # If any part is missing, leave id untouched; the row will be skipped later
            pass

    # Add helper ids for relations where convenient
    if dataset == "sales_order_schedule_lines":
        # helper id tying a schedule line back to its item
        if "salesOrder" in record and "salesOrderItem" in record:
            record["salesOrderItemId"] = f"{record['salesOrder']}|{record['salesOrderItem']}"

    return record


def load_nodes_from_file(
    session, dataset: str, file_path: str, label: str, id_field: str, cfg: Dict[str, Any]
) -> None:
    batch: List[Dict] = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            record = _prepare_record(dataset, cfg, record)
            if id_field not in record:
                continue
            # Sanitize all property values so they are valid Neo4j properties
            sanitized = {k: _sanitize_value(v) for k, v in record.items()}
            node_id = sanitized[id_field]
            row = {"id": node_id}
            row.update(sanitized)
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                _write_node_batch(session, label, batch)
                batch = []
    if batch:
        _write_node_batch(session, label, batch)


def _write_node_batch(session, label: str, rows: List[Dict]) -> None:
    cypher = f"""
    UNWIND $rows AS row
    MERGE (n:{label} {{id: row.id}})
    SET n += row
    """
    session.run(cypher, rows=rows)


def load_relationships_from_file(
    session,
    file_path: str,
    rel_type: str,
    from_label: str,
    to_label: str,
    from_key_in_row: str,
    to_key_in_row: str,
    dataset: str | None = None,
) -> None:
    batch: List[Dict] = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)

            # Apply the same dataset-specific transformations as for nodes
            # so composite ids and helper keys (e.g. salesOrderItemId) exist.
            if dataset and dataset in NODE_DATASETS:
                record = _prepare_record(dataset, NODE_DATASETS[dataset], record)

            if from_key_in_row not in record or to_key_in_row not in record:
                continue
            from_id = record[from_key_in_row]
            to_id = record[to_key_in_row]
            # skip records without usable ids (e.g. empty cancelledBillingDocument)
            if not from_id or not to_id:
                continue
            row = {
                "from_id": from_id,
                "to_id": to_id,
            }
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                _write_relationship_batch(session, rel_type, from_label, to_label, batch)
                batch = []
    if batch:
        _write_relationship_batch(session, rel_type, from_label, to_label, batch)


def _write_relationship_batch(
    session,
    rel_type: str,
    from_label: str,
    to_label: str,
    rows: List[Dict],
) -> None:
    cypher = f"""
    UNWIND $rows AS row
    MATCH (a:{from_label} {{id: row.from_id}})
    MATCH (b:{to_label} {{id: row.to_id}})
    MERGE (a)-[r:{rel_type}]->(b)
    """
    session.run(cypher, rows=rows)


def load_all_nodes(driver) -> None:
    with driver.session() as session:
        for dataset, cfg in NODE_DATASETS.items():
            pattern = cfg["glob"]
            label = cfg["label"]
            id_field = cfg["id_field"]
            for file_path in glob.glob(pattern):
                print(f"Loading nodes from {file_path} as {label}")
                load_nodes_from_file(session, dataset, file_path, label, id_field, cfg)


def load_all_relationships(driver) -> None:
    with driver.session() as session:
        for cfg in RELATION_DATASETS:
            pattern = cfg["source_glob"]
            rel_type = cfg["type"]
            from_label = cfg["from_label"]
            to_label = cfg["to_label"]
            from_key_in_row = cfg["from_key_in_row"]
            to_key_in_row = cfg["to_key_in_row"]
            dataset = cfg.get("dataset")
            for file_path in glob.glob(pattern):
                print(
                    f"Loading relationships {rel_type} from {from_label} to {to_label} "
                    f"using {file_path}"
                )
                load_relationships_from_file(
                    session,
                    file_path,
                    rel_type,
                    from_label,
                    to_label,
                    from_key_in_row,
                    to_key_in_row,
                    dataset,
                )


def main() -> None:
    driver = get_driver()
    try:
        load_all_nodes(driver)
        load_all_relationships(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
