
import json

def find_leads_mock(business_type, location, limit):
    print(f"Simulating lead finding for {business_type} in {location} with limit {limit}")
    leads = []
    for i in range(limit):
        leads.append({
            "name": f"Dental Practice {i+1}",
            "address": f"{i+1} Main St, {location}",
            "type": business_type,
            "phone": f"555-123-000{i+1}"
        })
    return leads

if __name__ == "__main__":
    business_type = "dental"
    location = "Flagstaff AZ"
    limit = 10

    found_leads = find_leads_mock(business_type, location, limit)

    with open("leads.json", "w") as f:
        json.dump(found_leads, f, indent=4)

    print(f"Saved {len(found_leads)} leads to leads.json")
