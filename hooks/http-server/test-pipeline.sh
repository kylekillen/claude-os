#!/bin/bash
# Integration test for the memory pipeline
# Tests: server up, health endpoint, observation insertion, session repair
# Usage: ./test-pipeline.sh

set -uo pipefail

PORT=9090
BASE="http://127.0.0.1:${PORT}"
DB="$HOME/.claude-mem/claude-mem.db"
PASS=0
FAIL=0

pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

echo "=== Memory Pipeline Integration Test ==="
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Test 1: Server is listening
echo "[1] Server reachable on :${PORT}"
if curl -sf "${BASE}/health" > /dev/null 2>&1; then
    pass "Server is running"
else
    fail "Server not reachable on :${PORT}"
    echo "ABORT: Server must be running. Try: launchctl load ~/Library/LaunchAgents/com.mojo.http-hooks-server.plist"
    exit 1
fi

# Test 2: Health endpoint returns valid JSON
echo "[2] Health endpoint"
HEALTH=$(curl -sf "${BASE}/health")
if echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='ok'" 2>/dev/null; then
    pass "Health returns status=ok"
    OBS_COUNT=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin)['observation_count'])")
    echo "       observation_count=${OBS_COUNT}"
else
    fail "Health endpoint returned bad data: ${HEALTH}"
fi

# Test 3: DB is writable
echo "[3] DB writable"
DB_WRITABLE=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('db_writable', False))")
if [ "$DB_WRITABLE" = "True" ]; then
    pass "DB is writable"
else
    fail "DB not writable"
fi

# Test 4: PostToolUse creates an observation (with a test session that doesn't exist yet)
echo "[4] PostToolUse observation insertion"
BEFORE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM observations;")
TEST_SESSION="integration-test-$(date +%s)"

curl -sf -X POST "${BASE}/hooks/PostToolUse" \
    -H "Content-Type: application/json" \
    -d "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"/tmp/test-pipeline-sentinel.txt\",\"old_string\":\"a\",\"new_string\":\"b\"},\"tool_response\":\"ok\",\"session_id\":\"${TEST_SESSION}\"}" > /dev/null

sleep 1

AFTER=$(sqlite3 "$DB" "SELECT COUNT(*) FROM observations;")
if [ "$AFTER" -gt "$BEFORE" ]; then
    pass "Observation inserted (${BEFORE} -> ${AFTER})"
else
    fail "Observation NOT inserted (still ${BEFORE})"
fi

# Test 5: Session auto-repair (check that the test session now has a memory_session_id)
echo "[5] Session auto-repair"
MSID=$(sqlite3 "$DB" "SELECT memory_session_id FROM sdk_sessions WHERE content_session_id='${TEST_SESSION}';")
if [ -n "$MSID" ]; then
    pass "Session created with memory_session_id=${MSID:0:8}..."
else
    fail "Session missing memory_session_id"
fi

# Test 6: Repair existing NULL sessions
echo "[6] NULL session repair on PostToolUse"
# Pick a real NULL session if one exists
NULL_SESSION=$(sqlite3 "$DB" "SELECT content_session_id FROM sdk_sessions WHERE memory_session_id IS NULL LIMIT 1;" 2>/dev/null || echo "")
if [ -n "$NULL_SESSION" ]; then
    curl -sf -X POST "${BASE}/hooks/PostToolUse" \
        -H "Content-Type: application/json" \
        -d "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"/tmp/repair-test.txt\",\"old_string\":\"a\",\"new_string\":\"b\"},\"tool_response\":\"ok\",\"session_id\":\"${NULL_SESSION}\"}" > /dev/null
    sleep 1
    REPAIRED=$(sqlite3 "$DB" "SELECT memory_session_id FROM sdk_sessions WHERE content_session_id='${NULL_SESSION}';")
    if [ -n "$REPAIRED" ]; then
        pass "Repaired session ${NULL_SESSION:0:8}... -> msid=${REPAIRED:0:8}..."
    else
        fail "Failed to repair session ${NULL_SESSION:0:8}..."
    fi
else
    pass "No NULL sessions to repair (all good)"
fi

# Cleanup test data
CLEANUP_MSID=$(sqlite3 "$DB" "SELECT memory_session_id FROM sdk_sessions WHERE content_session_id='${TEST_SESSION}';" 2>/dev/null || echo "")
if [ -n "$CLEANUP_MSID" ]; then
    sqlite3 "$DB" "DELETE FROM observations WHERE memory_session_id='${CLEANUP_MSID}';" 2>/dev/null || true
fi
sqlite3 "$DB" "DELETE FROM sdk_sessions WHERE content_session_id='${TEST_SESSION}';" 2>/dev/null || true

echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
[ "$FAIL" -eq 0 ] && echo "ALL TESTS PASSED" || echo "SOME TESTS FAILED"
exit $FAIL
