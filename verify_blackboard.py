#!/usr/bin/env python3
"""
Step 4 Verification: Call blackboard_read and verify it returns data
"""
import sys
sys.path.insert(0, '.')

print("=" * 70)
print("STEP 4 VERIFICATION: blackboard_read() Function Test")
print("=" * 70)

try:
    # Import the read function from blackboard
    from blackboard import read as bb_read, list_by_project
    print("\n✓ Successfully imported blackboard functions")

    # Call blackboard_read with the specified parameters
    print("\n[1] Calling blackboard_read(key='verify_tips', project='general')...")
    result = bb_read(key='verify_tips', project='general')

    print(f"[2] Function executed successfully")
    print(f"    Return type: {type(result).__name__}")
    print(f"    Return value: {result}")

    if result is not None and result != "":
        print(f"\n✓ VERIFICATION PASSED: Data found!")
        print(f"    - Entry exists: YES")
        print(f"    - Value type: {type(result).__name__}")
        print(f"    - Value length: {len(result)} characters")
        print(f"    - Content preview: {result[:100]}..." if len(result) > 100 else f"    - Full content: {result}")
        print(f"\n✓✓✓ Step 4 Complete: blackboard_read() successfully returns data")
        sys.exit(0)
    else:
        print(f"\n⚠ Entry not found - checking database contents...")

        # List all entries for the project
        entries = list_by_project(project='general')
        if entries:
            print(f"\nFound {len(entries)} entries in project 'general':")
            for entry in entries:
                val_preview = entry['value'][:80] + "..." if len(entry['value']) > 80 else entry['value']
                print(f"  - {entry['key']}: {val_preview}")
        else:
            print(f"\nNo entries found in project 'general'")

            # Check if database has any entries at all
            import sqlite3
            conn = sqlite3.connect('./data/blackboard.db')
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM entries")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT DISTINCT project FROM entries")
            projects = [row[0] for row in cursor.fetchall()]
            conn.close()

            print(f"\nDatabase stats:")
            print(f"  - Total entries: {total}")
            print(f"  - Projects in DB: {projects if projects else 'None'}")

        sys.exit(1)

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
