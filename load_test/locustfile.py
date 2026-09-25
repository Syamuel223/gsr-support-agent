"""
Load test for the GSR support agent API. Simulates realistic concurrent
traffic: a mix of question types, some from identified customers, some
anonymous, plus occasional signups -- rather than hammering one endpoint
with identical requests, which wouldn't tell you much about real usage.

Run (with the API already running on port 8000):
    pip install locust
    locust -f load_test/locustfile.py --host http://127.0.0.1:8000

Then open http://localhost:8089, set the number of users and spawn rate
(e.g. 100 users, spawn rate 10/s, matching the "100 concurrent users"
target), and start the test. Report the real p50/p95/p99 latency and
failure rate from the Locust UI -- don't estimate these numbers, run it
and read them off the dashboard.

Known constraint worth stating up front: GSR_MAX_CONCURRENT_AGENT_CALLS
(default 10, see api/main.py) intentionally queues requests beyond that
limit rather than rejecting them, to protect the LLM provider's rate
limit and DuckDB's single-writer constraint. At 100 concurrent simulated
users, expect p95 latency to reflect queuing time, not failures -- a
rising p95 with a near-zero failure rate is the semaphore working as
designed, not a bug. If you see actual failures (5xx), that's the signal
to investigate.
"""

import random
import uuid

from locust import HttpUser, between, task

TEXT_QUESTIONS = [
    "Where is my order?",
    "What's your return policy for electronics?",
    "How long does shipping usually take?",
    "Why was my payment declined?",
    "Can I return an item I no longer need?",
    "What's the difference between GSR Prime and regular?",
    "Do you ship internationally?",
    "How do I reset my password?",
    "What payment methods do you accept?",
    "Can I cancel my order?",
]

# a handful of real customer_ids from the synthetic dataset -- swap these
# for whatever your data/raw/gsr_customers.csv actually contains if you
# regenerated it with different ids
SAMPLE_CUSTOMER_IDS = [f"cust_{i:06d}" for i in range(0, 50)]


class GSRUser(HttpUser):
    # simulate a human pausing between messages, not a tight request loop
    wait_time = between(2, 8)

    def on_start(self):
        self.session_id = str(uuid.uuid4())
        # ~60% of simulated users are identified customers, ~40% anonymous
        self.customer_id = random.choice(SAMPLE_CUSTOMER_IDS) if random.random() < 0.6 else None

    @task(10)
    def ask_question(self):
        message = random.choice(TEXT_QUESTIONS)
        payload = {"session_id": self.session_id, "message": message}
        if self.customer_id:
            payload["customer_id"] = self.customer_id

        with self.client.post("/chat", json=payload, catch_response=True, name="/chat") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                # don't silently count queuing/slowness as failure unless
                # it's an actual error status
                resp.failure(f"status={resp.status_code} body={resp.text[:200]}")

    @task(1)
    def check_health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def new_customer_signup(self):
        rand_id = uuid.uuid4().hex[:8]
        self.client.post("/webhook/new-signup", json={
            "name": f"Load Test User {rand_id}",
            "email": f"loadtest_{rand_id}@example.com",
            "city": "Bengaluru",
            "state": "KA",
        }, name="/webhook/new-signup")
