"""
Generates synthetic operational data for GSR (GlobalShop Retail), a fictional
e-commerce company used as the sample company for this project.

This is the "live database" data -- customers, orders, payments, tickets,
returns -- as opposed to the static policy/FAQ documents in knowledge_base/,
which are used for RAG instead. Same split as the AskWarehouse project:
operational data gets queried via MCP tools, policy docs get retrieved via RAG.

Run:
    python data/generate_synthetic_data.py --n_customers 500 --n_orders 1500
"""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

random.seed(7)

FIRST_NAMES = ["Aditi", "Rahul", "Priya", "Arjun", "Sneha", "Vikram", "Ananya",
               "Karan", "Divya", "Rohan", "Neha", "Aman", "Pooja", "Siddharth",
               "Kavya", "Nikhil", "Ishita", "Varun", "Meera", "Aryan"]
LAST_NAMES = ["Sharma", "Verma", "Reddy", "Iyer", "Gupta", "Nair", "Singh",
              "Rao", "Mehta", "Patel", "Kumar", "Joshi", "Chatterjee", "Pillai"]

CITIES = [("Bengaluru", "KA"), ("Mumbai", "MH"), ("Delhi", "DL"), ("Chennai", "TN"),
          ("Hyderabad", "TS"), ("Pune", "MH"), ("Kolkata", "WB"), ("Ahmedabad", "GJ"),
          ("Jaipur", "RJ"), ("Lucknow", "UP")]

CATEGORIES = {
    "electronics": [("Wireless Earbuds", 1999, 4999), ("Smartphone", 12999, 89999),
                    ("Laptop", 34999, 129999), ("Smartwatch", 2999, 24999),
                    ("Bluetooth Speaker", 1499, 6999)],
    "fashion": [("Running Shoes", 1299, 5999), ("Cotton T-Shirt", 399, 1299),
                ("Denim Jacket", 1999, 4999), ("Backpack", 899, 3499)],
    "home_kitchen": [("Air Fryer", 3999, 9999), ("Non-stick Cookware Set", 1499, 4999),
                     ("Study Lamp", 599, 1999), ("Bedsheet Set", 799, 2499)],
    "books": [("Fiction Novel", 199, 699), ("Competitive Exam Guide", 349, 1299),
              ("Self-help Book", 249, 799)],
    "beauty_personal_care": [("Face Wash", 199, 599), ("Trimmer", 899, 2999),
                              ("Perfume", 799, 3999)],
}

ORDER_STATUSES_WEIGHTED = (
    ["delivered"] * 60 + ["shipped"] * 12 + ["out_for_delivery"] * 5 +
    ["processing"] * 8 + ["cancelled"] * 8 + ["returned"] * 7
)
PAYMENT_METHODS = ["upi", "credit_card", "debit_card", "net_banking", "cod",
                    "wallet"]
TICKET_CATEGORIES = ["order_status", "returns_refunds", "product_question",
                     "billing_payment", "account_issue", "delivery_delay",
                     "damaged_item", "wrong_item_received"]
TICKET_PRIORITY_WEIGHTED = ["low"] * 5 + ["medium"] * 4 + ["high"] * 1

START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 9, 1)


def random_date(start=START_DATE, end=END_DATE):
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def gen_id(prefix, n):
    return f"{prefix}_{n:06d}"


def generate(n_customers, n_products_per_cat, n_orders, n_tickets, out_dir):
    # --- customers ---
    customers = []
    for i in range(n_customers):
        city, state = random.choice(CITIES)
        signup = random_date()
        customers.append({
            "customer_id": gen_id("cust", i),
            "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
            "email": f"user{i}@example.com",
            "city": city,
            "state": state,
            "signup_date": signup,
            "tier": random.choices(["regular", "prime"], weights=[70, 30])[0],
        })
    df_customers = pd.DataFrame(customers)

    # --- products ---
    products = []
    pid = 0
    for category, items in CATEGORIES.items():
        for _ in range(n_products_per_cat):
            name, lo, hi = random.choice(items)
            price = round(random.uniform(lo, hi), 2)
            products.append({
                "product_id": gen_id("prod", pid),
                "product_name": name,
                "category": category,
                "price": price,
                "stock_qty": random.randint(0, 500),
                "warranty_months": random.choice([0, 0, 6, 12, 24]) if category == "electronics" else 0,
            })
            pid += 1
    df_products = pd.DataFrame(products)

    # --- orders, order_items, payments ---
    orders, items, payments = [], [], []
    item_counter = 0

    for i in range(n_orders):
        order_id = gen_id("ord", i)
        customer = df_customers.sample(1).iloc[0]
        order_date = random_date(start=max(START_DATE, customer["signup_date"]))
        status = random.choice(ORDER_STATUSES_WEIGHTED)

        estimated_delivery = order_date + timedelta(days=random.randint(3, 7))
        delivered_date = None
        if status in ("delivered", "returned"):
            late = random.random() < 0.2
            actual_days = random.randint(8, 15) if late else random.randint(2, 6)
            delivered_date = order_date + timedelta(days=actual_days)

        orders.append({
            "order_id": order_id,
            "customer_id": customer["customer_id"],
            "order_date": order_date,
            "status": status,
            "estimated_delivery_date": estimated_delivery,
            "delivered_date": delivered_date,
        })

        n_items = random.randint(1, 3)
        order_total = 0
        chosen_products = df_products.sample(n_items)
        for _, product in chosen_products.iterrows():
            qty = random.randint(1, 2)
            line_total = round(product["price"] * qty, 2)
            order_total += line_total
            items.append({
                "order_item_id": gen_id("item", item_counter),
                "order_id": order_id,
                "product_id": product["product_id"],
                "quantity": qty,
                "price_at_purchase": product["price"],
            })
            item_counter += 1

        payments.append({
            "payment_id": gen_id("pay", i),
            "order_id": order_id,
            "payment_method": random.choice(PAYMENT_METHODS),
            "amount": round(order_total, 2),
            "status": "refunded" if status == "returned" else (
                "failed" if status == "cancelled" and random.random() < 0.3 else "completed"
            ),
        })

    df_orders = pd.DataFrame(orders)
    df_items = pd.DataFrame(items)
    df_payments = pd.DataFrame(payments)

    # --- returns (only for orders with status == returned) ---
    returns = []
    return_reasons = ["defective_item", "wrong_item_received", "no_longer_needed",
                       "better_price_found", "item_damaged_in_transit", "size_issue"]
    returned_orders = df_orders[df_orders["status"] == "returned"]
    rid = 0
    for _, order in returned_orders.iterrows():
        order_items_for_order = df_items[df_items["order_id"] == order["order_id"]]
        if order_items_for_order.empty:
            continue
        item = order_items_for_order.sample(1).iloc[0]
        requested_at = order["delivered_date"] + timedelta(days=random.randint(1, 6))
        returns.append({
            "return_id": gen_id("ret", rid),
            "order_id": order["order_id"],
            "order_item_id": item["order_item_id"],
            "reason": random.choice(return_reasons),
            "status": random.choices(["completed", "approved", "requested", "rejected"],
                                      weights=[50, 20, 20, 10])[0],
            "requested_at": requested_at,
        })
        rid += 1
    df_returns = pd.DataFrame(returns)

    # --- support tickets ---
    tickets = []
    for i in range(n_tickets):
        customer = df_customers.sample(1).iloc[0]
        # 70% of tickets are tied to a real order of that customer, 30% general
        customer_orders = df_orders[df_orders["customer_id"] == customer["customer_id"]]
        order_id = None
        if len(customer_orders) > 0 and random.random() < 0.7:
            order_id = customer_orders.sample(1).iloc[0]["order_id"]

        category = random.choice(TICKET_CATEGORIES)
        created_at = random_date()
        status = random.choices(["resolved", "open", "escalated"], weights=[65, 20, 15])[0]
        resolved_at = created_at + timedelta(hours=random.randint(1, 72)) if status == "resolved" else None

        tickets.append({
            "ticket_id": gen_id("tkt", i),
            "customer_id": customer["customer_id"],
            "order_id": order_id,
            "category": category,
            "priority": random.choice(TICKET_PRIORITY_WEIGHTED),
            "status": status,
            "created_at": created_at,
            "resolved_at": resolved_at,
        })
    df_tickets = pd.DataFrame(tickets)

    out_dir.mkdir(parents=True, exist_ok=True)
    df_customers.to_csv(out_dir / "gsr_customers.csv", index=False)
    df_products.to_csv(out_dir / "gsr_products.csv", index=False)
    df_orders.to_csv(out_dir / "gsr_orders.csv", index=False)
    df_items.to_csv(out_dir / "gsr_order_items.csv", index=False)
    df_payments.to_csv(out_dir / "gsr_payments.csv", index=False)
    df_returns.to_csv(out_dir / "gsr_returns.csv", index=False)
    df_tickets.to_csv(out_dir / "gsr_tickets.csv", index=False)

    print(f"Generated synthetic GSR dataset in {out_dir}/")
    print(f"  customers: {len(df_customers)}")
    print(f"  products:  {len(df_products)}")
    print(f"  orders:    {len(df_orders)}")
    print(f"  order_items: {len(df_items)}")
    print(f"  payments:  {len(df_payments)}")
    print(f"  returns:   {len(df_returns)}")
    print(f"  tickets:   {len(df_tickets)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_customers", type=int, default=500)
    parser.add_argument("--n_products_per_cat", type=int, default=10)
    parser.add_argument("--n_orders", type=int, default=1500)
    parser.add_argument("--n_tickets", type=int, default=400)
    parser.add_argument("--out_dir", type=str, default="data/raw")
    args = parser.parse_args()

    generate(
        n_customers=args.n_customers,
        n_products_per_cat=args.n_products_per_cat,
        n_orders=args.n_orders,
        n_tickets=args.n_tickets,
        out_dir=Path(args.out_dir),
    )
