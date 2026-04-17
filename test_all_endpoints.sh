#!/bin/bash
# Comprehensive API Endpoint Test Script
BASE="${BASE:-http://127.0.0.1:5001}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@gmail.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123!}"

LOGIN_RESPONSE=$(curl -s -X POST "$BASE/api/users/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}")

TOKEN=$(printf '%s' "$LOGIN_RESPONSE" | python3 -c "
import json, sys
try:
    payload = json.load(sys.stdin)
    data = payload.get('data') or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    print(data.get('token') or data.get('remember_token') or data.get('access_token') or '')
except Exception:
    print('')
")

if [ -z "$TOKEN" ]; then
  echo "Failed to authenticate test script."
  echo "$LOGIN_RESPONSE"
  exit 1
fi

AUTH="Authorization: Bearer $TOKEN"
PASS=0
FAIL=0
ERRORS=""

check() {
  local name="$1"
  local response="$2"
  # Check if response contains "code":1 or "success":true
  echo "$response" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  if d.get('code')==1 or d.get('success')==True:
    print('PASS')
  else:
    print('FAIL: '+json.dumps(d.get('message','unknown')))
except:
  print('FAIL: not JSON')
" 2>/dev/null
}

test_endpoint() {
  local name="$1"
  local method="$2"
  local url="$3"
  local data="$4"

  if [ "$method" = "GET" ]; then
    resp=$(curl -s "$BASE$url" -H "$AUTH")
  else
    resp=$(curl -s -X "$method" "$BASE$url" -H "$AUTH" -H "Content-Type: application/json" -d "$data")
  fi

  result=$(echo "$resp" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  if d.get('code')==1 or d.get('success')==True:
    print('PASS')
  else:
    print('FAIL: '+str(d.get('message','unknown'))[:80])
except Exception as e:
  print('FAIL: '+str(e)[:80])
" 2>/dev/null)

  if [[ "$result" == PASS* ]]; then
    echo "  PASS  $name"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $name  -> $result"
    FAIL=$((FAIL+1))
    ERRORS="$ERRORS\n  $name: $result"
  fi
}

test_expected_error() {
  local name="$1"
  local method="$2"
  local url="$3"
  local data="$4"
  local expected_message="$5"

  if [ "$method" = "GET" ]; then
    resp=$(curl -s "$BASE$url" -H "$AUTH")
  else
    resp=$(curl -s -X "$method" "$BASE$url" -H "$AUTH" -H "Content-Type: application/json" -d "$data")
  fi

  result=$(printf '%s' "$resp" | python3 -c "
import sys, json
try:
  d = json.load(sys.stdin)
  msg = str(d.get('message', ''))
  ok = d.get('code') != 1 and '$expected_message' in msg
  print('PASS' if ok else 'FAIL: ' + json.dumps(d))
except Exception as e:
  print('FAIL: ' + str(e)[:80])
" 2>/dev/null)

  if [[ "$result" == PASS* ]]; then
    echo "  PASS  $name"
    PASS=$((PASS+1))
  else
    echo "  FAIL  $name  -> $result"
    FAIL=$((FAIL+1))
    ERRORS="$ERRORS\n  $name: $result"
  fi
}

echo "================================================================"
echo "  NegoRide Canada API - Comprehensive Endpoint Tests"
echo "================================================================"
echo ""
echo "Authenticated as $ADMIN_EMAIL"
echo ""

echo "--- AUTH & PROFILE ---"
test_endpoint "POST /api/users/login" "POST" "/api/users/login" '{"email":"admin@gmail.com","password":"Admin123!"}'
test_endpoint "GET  /api/users/me" "GET" "/api/users/me"
test_endpoint "POST /api/profile/update" "POST" "/api/profile/update" '{"first_name":"Admin"}'

echo ""
echo "--- ADMIN DASHBOARD & ANALYTICS ---"
test_endpoint "GET  /api/admin/dashboard" "GET" "/api/admin/dashboard"
test_endpoint "GET  /api/admin/analytics" "GET" "/api/admin/analytics?period=month"
test_endpoint "GET  /api/admin/revenue-chart" "GET" "/api/admin/revenue-chart?days=30"
test_endpoint "GET  /api/admin/user-growth" "GET" "/api/admin/user-growth?days=365"
test_endpoint "GET  /api/admin/system/health" "GET" "/api/admin/system/health"
test_endpoint "GET  /api/admin/system/counts" "GET" "/api/admin/system/counts"

echo ""
echo "--- ADMIN USERS ---"
test_endpoint "GET  /api/admin/users" "GET" "/api/admin/users?per_page=5"
test_endpoint "GET  /api/admin/users?type=Driver" "GET" "/api/admin/users?user_type=Driver&per_page=3"
test_endpoint "GET  /api/admin/users?search=admin" "GET" "/api/admin/users?search=admin"
test_endpoint "GET  /api/admin/users/1 (detail)" "GET" "/api/admin/users/1"
test_expected_error "GET  /api/admin/users/999 (expected missing user)" "GET" "/api/admin/users/999" "" "User not found"
test_endpoint "POST /api/admin/users/2/update" "POST" "/api/admin/users/2/update" '{"first_name":"TestUpdate"}'
test_endpoint "POST /api/admin/users/1/reset-password" "POST" "/api/admin/users/1/reset-password" '{"new_password":"Admin123!"}'
test_endpoint "GET  /api/admin/users/1/wallet" "GET" "/api/admin/users/1/wallet"

echo ""
echo "--- ADMIN NEGOTIATIONS ---"
test_endpoint "GET  /api/admin/negotiations" "GET" "/api/admin/negotiations"
test_endpoint "GET  /api/admin/negotiations?status=Pending" "GET" "/api/admin/negotiations?status=Pending"

echo ""
echo "--- ADMIN TRIPS ---"
test_endpoint "GET  /api/admin/trips" "GET" "/api/admin/trips"
test_endpoint "GET  /api/admin/trips?status=Active" "GET" "/api/admin/trips?status=Active"

echo ""
echo "--- ADMIN BOOKINGS ---"
test_endpoint "GET  /api/admin/bookings" "GET" "/api/admin/bookings"
test_endpoint "GET  /api/admin/trip-bookings" "GET" "/api/admin/trip-bookings"

echo ""
echo "--- ADMIN PAYMENTS ---"
test_endpoint "GET  /api/admin/payments" "GET" "/api/admin/payments"

echo ""
echo "--- ADMIN WALLETS & TRANSACTIONS ---"
test_endpoint "GET  /api/admin/wallets" "GET" "/api/admin/wallets"
test_endpoint "GET  /api/admin/transactions" "GET" "/api/admin/transactions"

echo ""
echo "--- ADMIN PAYOUT REQUESTS ---"
test_endpoint "GET  /api/admin/payout-requests" "GET" "/api/admin/payout-requests"

echo ""
echo "--- ADMIN CHATS ---"
test_endpoint "GET  /api/admin/chats" "GET" "/api/admin/chats"

echo ""
echo "--- ADMIN COMPANIES ---"
test_endpoint "GET  /api/admin/companies" "GET" "/api/admin/companies"

echo ""
echo "--- ADMIN ROUTE STAGES ---"
test_endpoint "GET  /api/admin/route-stages" "GET" "/api/admin/route-stages"

echo ""
echo "--- MOBILE: NEGOTIATIONS ---"
test_endpoint "GET  /api/negotiations" "GET" "/api/negotiations"

echo ""
echo "--- MOBILE: TRIPS ---"
test_endpoint "GET  /api/trips" "GET" "/api/trips"

echo ""
echo "--- MOBILE: BOOKINGS ---"
test_endpoint "GET  /api/bookings" "GET" "/api/bookings"

echo ""
echo "--- MOBILE: WALLET ---"
test_endpoint "GET  /api/wallet" "GET" "/api/wallet"
test_endpoint "GET  /api/wallet/transactions" "GET" "/api/wallet/transactions"
test_endpoint "GET  /api/wallet/summary" "GET" "/api/wallet/summary"

echo ""
echo "--- MOBILE: PAYOUT ACCOUNT ---"
test_endpoint "GET  /api/payout-account" "GET" "/api/payout-account"

echo ""
echo "--- MOBILE: PAYOUT REQUESTS ---"
test_endpoint "GET  /api/payout-requests" "GET" "/api/payout-requests"
test_endpoint "GET  /api/payout-requests/statistics" "GET" "/api/payout-requests/statistics"

echo ""
echo "--- MOBILE: CHAT ---"
test_endpoint "GET  /api/chat-heads" "GET" "/api/chat-heads"

echo ""
echo "--- MOBILE: LOCATION ---"
test_endpoint "POST /api/update-online-status" "POST" "/api/update-online-status" '{}'

echo ""
echo "--- RESOURCES (PUBLIC) ---"
test_endpoint "GET  /api/route-stages" "GET" "/api/route-stages"
test_endpoint "GET  /api/drivers" "GET" "/api/drivers"
test_endpoint "GET  /api/saccos" "GET" "/api/saccos"

echo ""
echo "================================================================"
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "================================================================"
if [ $FAIL -gt 0 ]; then
  echo "  FAILURES:"
  echo -e "$ERRORS"
fi
