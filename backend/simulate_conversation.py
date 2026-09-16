import sys
import os

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json
from fastapi.testclient import TestClient
from main import app
import database


def run_simulation():
    print("=" * 70)
    print("TEST SUITE: WhatsApp AI Camp Assistant (PoC) - Scenario Simulation")
    print("=" * 70)

    test_phone = "905551234567@c.us"
    
    # Reset before starting test run
    database.clear_history(test_phone)

    scenarios = [
        {
            "name": "1. Health & Readiness Check",
            "type": "GET",
            "url": "/health",
            "body": None,
        },
        {
            "name": "2. Check-in Hours Query (Turn 1)",
            "type": "POST",
            "url": "/webhook",
            "body": {
                "phone": test_phone,
                "message": "Yarın sabah giriş kaçta başlıyor?",
            },
        },
        {
            "name": "3. Context Retention Test (Turn 2 - Deduce context without repeating)",
            "type": "POST",
            "url": "/webhook",
            "body": {
                "phone": test_phone,
                "message": "Peki çadırı siz mi veriyorsunuz?",
            },
        },
        {
            "name": "4. Strict Guardrail / Anti-Hallucination Test (Out-of-boundary question)",
            "type": "POST",
            "url": "/webhook",
            "body": {
                "phone": test_phone,
                "message": "Yanımda evcil iguana getirebilir miyim?",
            },
        },
        {
            "name": "5. Session Reset Test (/reset command)",
            "type": "POST",
            "url": "/webhook",
            "body": {
                "phone": test_phone,
                "message": "/reset",
            },
        },
    ]

    results = []

    with TestClient(app) as client:
        for idx, scenario in enumerate(scenarios, 1):
            print(f"\n[Step {idx}] {scenario['name']}")
            if scenario["type"] == "GET":
                response = client.get(scenario["url"])
            else:
                print(f"  > WhatsApp User ({test_phone}): \"{scenario['body']['message']}\"")
                response = client.post(scenario["url"], json=scenario["body"])

            status_code = response.status_code
            data = response.json()
            
            if scenario["type"] == "GET":
                print(f"  < Response (HTTP {status_code}): {json.dumps(data, ensure_ascii=False)}")
            else:
                reply = data.get("reply", "")
                print(f"  < Assistant Reply: \"{reply}\"")

            passed = (status_code == 200)
            results.append({
                "scenario": scenario["name"],
                "status_code": status_code,
                "data": data,
                "passed": passed,
            })

    # Verify database state after /reset
    remaining_history = database.get_history(test_phone)
    print("\n" + "=" * 70)
    print("SIMULATION SUMMARY")
    print("=" * 70)
    for r in results:
        indicator = "[PASS]" if r["passed"] else "[FAIL]"
        print(f"{indicator} - {r['scenario']}")
    
    print(f"\nFinal SQLite History Count for {test_phone}: {len(remaining_history)} (Expected: 0)")
    print("=" * 70)


if __name__ == "__main__":
    run_simulation()
