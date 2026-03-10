#!/bin/bash
# Call Flagstaff restaurant leads via OpenClaw AI Sales Caller
# Usage: ./call_leads.sh [optional: business_name]

cd ./

if [ -n "$1" ]; then
    echo "Calling specific lead: $1"
    python3 -c "
import asyncio, sys, os
sys.path.insert(0, '.')
from sales_caller import call_lead
import json, glob

# Find matching lead
target = '$1'.lower()
for f in glob.glob('data/leads/*.json'):
    with open(f) as fh:
        lead = json.load(fh)
    if target in lead.get('business_name', '').lower():
        print(f'Calling {lead[\"business_name\"]} at {lead[\"phone\"]}...')
        result = asyncio.run(call_lead(
            phone=lead['phone'],
            business_name=lead['business_name'],
            business_type=lead.get('business_type', 'restaurant'),
            owner_name=lead.get('owner_name', ''),
        ))
        if result.get('success'):
            print(f'Call started! ID: {result[\"call_id\"]}')
        else:
            print(f'Failed: {result.get(\"error\", \"unknown\")}')
        sys.exit(0)
print(f'No lead found matching: $1')
"
else
    echo "Calling all Flagstaff leads (5 second delay between calls)..."
    python3 -c "
import asyncio, sys, os, time
sys.path.insert(0, '.')
from sales_caller import call_lead
import json, glob

leads = []
for f in sorted(glob.glob('data/leads/*.json')):
    with open(f) as fh:
        lead = json.load(fh)
    if lead.get('phone') and lead.get('status') != 'called':
        leads.append(lead)

print(f'Found {len(leads)} leads with phone numbers\n')
for i, lead in enumerate(leads, 1):
    print(f'{i}. Calling {lead[\"business_name\"]} at {lead[\"phone\"]}...')
    try:
        result = asyncio.run(call_lead(
            phone=lead['phone'],
            business_name=lead['business_name'],
            business_type=lead.get('business_type', 'restaurant'),
            owner_name=lead.get('owner_name', ''),
        ))
        if result.get('success'):
            print(f'   Started! Call ID: {result[\"call_id\"]}')
        else:
            print(f'   Failed: {result.get(\"error\", \"unknown\")}')
    except Exception as e:
        print(f'   Error: {e}')
    if i < len(leads):
        print(f'   Waiting 5 seconds...')
        time.sleep(5)

print(f'\nDone! {len(leads)} calls initiated.')
"
fi
