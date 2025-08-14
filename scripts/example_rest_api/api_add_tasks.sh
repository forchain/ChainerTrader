#!/usr/bin/env bash

curl -X POST "http://127.0.0.1:8000/add_tasks" \
     -H "Content-Type: application/json" \
     -d '[{"task_type": "DEBUG","limit":10}]'


