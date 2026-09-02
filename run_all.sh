#!/bin/bash
# يشغّل ChannelForge كاملًا داخل عملية واحدة وعلى منفذ واحد.
# Render يمرر قيمة PORT تلقائيًا.

set -e

exec uvicorn app:app --host 0.0.0.0 --port "$PORT"