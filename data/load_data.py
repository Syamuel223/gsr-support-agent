"""
Loads GSR operational CSVs from data/raw/ into a DuckDB warehouse file.

This is the "live" operational database that MCP tools query (order status,
customer lookup, tickets, returns) -- separate from the RAG knowledge base
in knowledge_base/, which holds policy/FAQ docs.

Run:
    python data/load_data.py
    python data/load_data.py --db_path data/gsr.duckdb
"""

import argparse
from pathlib import Path

import duckdb

TABLES = {
    "customers": "gsr_customers.csv",
    "products": "gsr_products.csv",
    "orders": "gsr_orders.csv",
    "order_items": "gsr_order_items.csv",
    "payments": "gsr_payments.csv",
    "returns": "gsr_returns.csv",
    "tickets": "gsr_tickets.csv",
}


def load(raw_dir: Path, db_path: Path):
    con = duckdb.connect(str(db_path))
    loaded = set()

    for table_name, csv_file in TABLES.items():
        csv_path = raw_dir / csv_file
        if not csv_path.exists():
            print(f"  [skip] {csv_file} not found in {raw_dir}/")
            continue

        con.sql(f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_csv_auto('{csv_path.as_posix()}')
        """)
        row_count = con.sql(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"  [ok] {table_name:<16} <- {csv_file}  ({row_count} rows)")
        loaded.add(table_name)

    print("\nIntegrity spot-checks:")
    if {"order_items", "orders"} <= loaded:
        orphan_items = con.sql("""
            SELECT COUNT(*) FROM order_items oi
            LEFT JOIN orders o ON oi.order_id = o.order_id
            WHERE o.order_id IS NULL
        """).fetchone()[0]
        print(f"  order_items with no matching order: {orphan_items}")

    if {"tickets", "customers"} <= loaded:
        orphan_tickets = con.sql("""
            SELECT COUNT(*) FROM tickets t
            LEFT JOIN customers c ON t.customer_id = c.customer_id
            WHERE c.customer_id IS NULL
        """).fetchone()[0]
        print(f"  tickets with no matching customer: {orphan_tickets}")

    if "tickets" in loaded:
        open_tickets = con.sql(
            "SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'escalated')"
        ).fetchone()[0]
        print(f"  currently open/escalated tickets: {open_tickets}")

    con.close()
    print(f"\nWarehouse ready at: {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw_dir", type=str, default="data/raw")
    parser.add_argument("--db_path", type=str, default="data/gsr.duckdb")
    args = parser.parse_args()

    load(Path(args.raw_dir), Path(args.db_path))
