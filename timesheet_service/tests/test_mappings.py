import sys
import os
import json

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler_service import SchedulerService

def test_mappings():
    # 1. Load Config
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)

    # 2. Init Service
    service = SchedulerService(config)
    
    # 3. Test Cases
    test_cases = [
        {
            "name": "Exact ID Match (EPA SV)",
            "data": {"entities_id": "150", "ticket_title": "Algo", "entity_fullname": "Cualquiera"},
            "expected_client": "EPA SV"
        },
        {
            "name": "Fullname Heuristic (EPA VE)",
            "data": {"entities_id": "999", "ticket_title": "Algo", "entity_fullname": "Root Entity > EPA VE > Soporte"},
            "expected_client": "EPA VE"
        },
        {
            "name": "Title Heuristic (Bamerica)",
            "data": {"entities_id": "999", "ticket_title": "Soporte para bamerica", "entity_fullname": "Intelix"},
            "expected_client": "Bamerica"
        },
        {
            "name": "Fallback (Config Default)",
            "data": {"entities_id": "999", "ticket_title": "Revision general", "entity_fullname": "Intelix"},
            "expected_client": "Comercializadoras EPA"
        }
    ]

    print("\n" + "="*60)
    print(" PRUEBA DE MAPEOS DINÁMICOS (mappings.json)")
    print("="*60)

    passed = 0
    for case in test_cases:
        result = service._determine_ticket_metadata(case["data"])
        actual_client = result.get("client")
        
        # We check client because result can vary based on project mappings
        status = "PASSED" if actual_client == case["expected_client"] else "FAILED"
        print(f"[{status}] {case['name']}")
        if actual_client != case["expected_client"]:
            print(f"    - Expected: {case['expected_client']}")
            print(f"    - Actual: {actual_client}")
        else:
            passed += 1
            print(f"    - Result: {result.get('client')} | {result.get('project')}")

    print("="*60)
    print(f" Resultado final: {passed}/{len(test_cases)} pruebas superadas.")
    print("="*60 + "\n")

if __name__ == "__main__":
    test_mappings()
