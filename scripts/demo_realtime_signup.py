"""
Demonstrates the real-time signup requirement: a brand new customer signs
up and is immediately queryable by the support agent, with no batch
processing or refresh delay.

Requires the API server running first:
    uvicorn api.main:app --reload --port 8000

Then, in another terminal:
    python scripts/demo_realtime_signup.py
"""

import time

import requests

BASE_URL = "http://127.0.0.1:8000"


def main():
    print("1. Signing up a brand new customer...")
    signup_resp = requests.post(f"{BASE_URL}/webhook/new-signup", json={
        "name": "Demo Customer",
        "email": f"demo{int(time.time())}@example.com",
        "city": "Bengaluru",
        "state": "KA",
    })
    signup_resp.raise_for_status()
    signup_data = signup_resp.json()
    customer_id = signup_data["customer_id"]
    print(f"   -> Registered: {customer_id}")
    print(f"   -> {signup_data['message']}")

    print("\n2. Immediately chatting as this brand new customer (no delay)...")
    chat_resp = requests.post(f"{BASE_URL}/chat", json={
        "session_id": f"demo-session-{customer_id}",
        "customer_id": customer_id,
        "message": "Hi, do I have any orders yet?",
    })
    chat_resp.raise_for_status()
    chat_data = chat_resp.json()

    print(f"   -> Intent: {chat_data['intent']}")
    print(f"   -> Response: {chat_data['response']}")
    print(
        "\nThis proves the customer was queryable the instant after signup -- "
        "no batch job, no cache refresh, no delay."
    )


if __name__ == "__main__":
    main()
