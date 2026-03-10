#!/bin/sh
cd ./
python3 -m pytest test_n8n_webhook.py --tb=short -v > ./test_results.txt 2>&1
echo "Exit code: $?" >> ./test_results.txt
