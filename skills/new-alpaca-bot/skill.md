---
name: new-alpaca-bot
description: Use this skill when creating a new trading bot that will use Alpaca paper trading. Ensures proper segregation from other bots sharing the same account.
---

# Creating a New Alpaca Paper Trading Bot (v3)

This skill ensures new trading bots are properly segregated from existing bots sharing the same Alpaca paper trading account.

**Version 3** - Addresses race conditions, atomic file operations, and partial fill handling.

## Core Principles

1. **Unlimited Paper Capital**: Paper money is arbitrary. Each bot gets its own $100K virtual allocation.
2. **Order Tagging**: Every order MUST have a unique `client_order_id` prefix to identify ownership.
3. **Position Isolation**: Bots track only their own positions, even if multiple bots own the same stock.
4. **No Cross-Contamination**: A bot NEVER sells shares it didn't buy, even accidentally.
5. **Atomic Operations**: All file operations use locks held for the entire read-modify-write cycle.

---

## Step 1: Register a Unique Bot Prefix

**CRITICAL**: Before writing any code, register your prefix to avoid collisions.

### Check Existing Prefixes

Query the prefix registry or check this list:

| Prefix | Bot Name | Location | Strategy |
|--------|----------|----------|----------|
| `HF` | Hedge Fund Bot | `~/claude-hedge-fund/` | AI energy thesis |
| `MOM` | Momentum Bot | `~/momentum-bot/` | 12-1 S&P momentum |

### Register Your Prefix (with file locking)

Add your bot to the registry before proceeding:

```bash
# Add to ~/.config/personal-os/alpaca-bot-registry.json
python3 << 'EOF'
import json
import fcntl
from pathlib import Path
from datetime import datetime

registry_path = Path.home() / ".config/personal-os/alpaca-bot-registry.json"
registry_path.parent.mkdir(parents=True, exist_ok=True)

# Your new bot info
new_bot = {
    "prefix": "XXX",  # YOUR 2-4 CHARACTER PREFIX (no dash)
    "name": "Your Bot Name",
    "path": "~/your-bot-name/",
    "strategy": "Brief description",
    "created": datetime.now().isoformat()
}

# Atomic read-modify-write with lock held throughout
if registry_path.exists():
    with open(registry_path, 'r+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            registry = json.load(f)
            existing_prefixes = [b["prefix"] for b in registry["bots"]]
            if new_bot["prefix"] in existing_prefixes:
                raise ValueError(f"PREFIX COLLISION: {new_bot['prefix']} already registered!")
            registry["bots"].append(new_bot)
            f.seek(0)
            f.truncate()
            json.dump(registry, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
else:
    # Create new registry with lock
    with open(registry_path, 'w') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            registry = {"bots": [new_bot]}
            json.dump(registry, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

print(f"✓ Registered prefix: {new_bot['prefix']}")
EOF
```

### Prefix Format Rules

- **2-4 uppercase characters** (e.g., `VAL`, `DIV`, `ARB`, `MEAN`)
- **NO trailing dash** - the dash is added in code
- **Descriptive** of strategy when possible

---

## Step 2: Implement Order Tagging

**CRITICAL**: Every order MUST include a tagged `client_order_id`.

### Required: alpaca_client.py

```python
"""
Alpaca client with order tagging for bot isolation.

ORDER TAGGING: All orders use client_order_id prefix "{PREFIX}-"
This enables tracking ownership when multiple bots share an account.
"""

import os
import uuid
import time
from typing import Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from dotenv import load_dotenv

# Load credentials
load_dotenv(os.path.expanduser("~/.config/personal-os/alpaca.env"))


class AlpacaClient:
    # YOUR UNIQUE PREFIX - NO TRAILING DASH
    BOT_PREFIX = "XXX"  # CHANGE THIS to your registered prefix

    def __init__(self, paper: bool = True):
        self.client = TradingClient(
            api_key=os.getenv("ALPACA_API_KEY"),
            secret_key=os.getenv("ALPACA_SECRET_KEY"),
            paper=paper
        )

    def _generate_order_id(self) -> str:
        """
        Generate unique client_order_id with bot prefix.
        Format: {PREFIX}-{12 hex chars}
        Example: VAL-a1b2c3d4e5f6
        """
        return f"{self.BOT_PREFIX}-{uuid.uuid4().hex[:12]}"

    def is_our_order(self, client_order_id: Optional[str]) -> bool:
        """Check if an order belongs to this bot based on prefix."""
        if not client_order_id:
            return False
        return client_order_id.startswith(f"{self.BOT_PREFIX}-")

    def _status_str(self, status) -> str:
        """
        Normalize order status to string. Handles both enum and string types.
        Alpaca SDK may return OrderStatus enum or string depending on version.
        """
        return str(status).lower().replace("orderstatus.", "")

    def wait_for_fill(self, order_id: str, timeout_seconds: int = 60) -> dict:
        """
        Wait for an order to fill. CRITICAL for accurate position tracking.

        Returns filled order details or raises exception on timeout/failure.
        Always includes 'side' field for recovery purposes.
        v3: Includes retry logic for network errors.
        """
        start = time.time()
        consecutive_errors = 0
        max_consecutive_errors = 3

        while time.time() - start < timeout_seconds:
            try:
                order = self.client.get_order_by_id(order_id)
                consecutive_errors = 0  # Reset on success
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    # Too many errors - return unknown state for manual reconciliation
                    return {
                        "status": "error_unknown_state",
                        "order_id": order_id,
                        "error": str(e),
                        "filled_qty": 0,
                        "filled_avg_price": 0,
                        "needs_reconciliation": True  # Flag for recovery
                    }
                # Exponential backoff: 2, 4, 8 seconds
                time.sleep(min(2 ** consecutive_errors, 10))
                continue

            status = self._status_str(order.status)

            if status == "filled":
                return {
                    "status": "filled",
                    "symbol": order.symbol,
                    "side": self._status_str(order.side),
                    "filled_qty": float(order.filled_qty),
                    "filled_avg_price": float(order.filled_avg_price),
                    "client_order_id": order.client_order_id,
                    "order_id": str(order.id)
                }
            elif status in ["canceled", "expired", "rejected"]:
                filled_qty = float(order.filled_qty) if order.filled_qty else 0
                return {
                    "status": status,
                    "symbol": order.symbol,
                    "side": self._status_str(order.side),
                    "filled_qty": filled_qty,
                    "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else 0,
                    "client_order_id": order.client_order_id,
                    "order_id": str(order.id),
                    "partial_fill": filled_qty > 0  # Flag for recovery
                }
            elif status == "partially_filled":
                # For partial fills, continue waiting but could handle differently
                pass

            time.sleep(1)

        # Timeout - return current state with partial fill info
        try:
            order = self.client.get_order_by_id(order_id)
            status = self._status_str(order.status)
            filled_qty = float(order.filled_qty) if order.filled_qty else 0
            return {
                "status": f"timeout_{status}",
                "symbol": order.symbol,
                "side": self._status_str(order.side),
                "filled_qty": filled_qty,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else 0,
                "client_order_id": order.client_order_id,
                "order_id": str(order.id),
                "partial_fill": filled_qty > 0  # Flag for recovery
            }
        except Exception as e:
            return {
                "status": "timeout_error_unknown_state",
                "order_id": order_id,
                "error": str(e),
                "filled_qty": 0,
                "filled_avg_price": 0,
                "needs_reconciliation": True
            }

    def buy(self, symbol: str, qty: float = None, notional: float = None,
            wait_for_fill: bool = True) -> dict:
        """
        Submit a BUY order with proper tagging.

        Args:
            symbol: Stock ticker
            qty: Number of shares (use this OR notional)
            notional: Dollar amount (use this OR qty)
            wait_for_fill: If True, wait for fill before returning

        Returns:
            Dict with order details including filled_qty and filled_avg_price
        """
        client_order_id = self._generate_order_id()

        order_data = {
            "symbol": symbol,
            "side": OrderSide.BUY,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": client_order_id,
        }

        if qty:
            order_data["qty"] = qty
        elif notional:
            order_data["notional"] = round(notional, 2)
        else:
            raise ValueError("Must specify qty or notional")

        request = MarketOrderRequest(**order_data)
        order = self.client.submit_order(request)

        if wait_for_fill:
            return self.wait_for_fill(str(order.id))

        return {
            "status": "submitted",
            "order_id": str(order.id),
            "client_order_id": client_order_id
        }

    def sell(self, symbol: str, qty: float, wait_for_fill: bool = True) -> dict:
        """
        Submit a SELL order with proper tagging.

        ALWAYS specify exact quantity - NEVER use close_position API!

        Args:
            symbol: Stock ticker
            qty: Exact number of shares to sell
            wait_for_fill: If True, wait for fill before returning
        """
        client_order_id = self._generate_order_id()

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        order = self.client.submit_order(request)

        if wait_for_fill:
            return self.wait_for_fill(str(order.id))

        return {
            "status": "submitted",
            "order_id": str(order.id),
            "client_order_id": client_order_id
        }

    def get_our_orders(self, status: str = "all", limit: int = 500) -> list:
        """Get only orders belonging to this bot (filtered by prefix)."""
        if status == "all":
            query_status = QueryOrderStatus.ALL
        elif status == "open":
            query_status = QueryOrderStatus.OPEN
        elif status == "closed":
            query_status = QueryOrderStatus.CLOSED
        else:
            query_status = QueryOrderStatus.ALL

        all_orders = self.client.get_orders(
            filter=GetOrdersRequest(status=query_status, limit=limit)
        )
        return [o for o in all_orders if self.is_our_order(str(o.client_order_id))]

    def get_account(self):
        """Get account info (shared across all bots - use for reference only)."""
        return self.client.get_account()
```

### FORBIDDEN PATTERNS - NEVER DO THESE:

```python
# ❌ NEVER: Order without client_order_id
order = MarketOrderRequest(symbol="AAPL", qty=10, side=OrderSide.BUY)

# ❌ NEVER: close_position() - closes ALL shares including other bots'
client.close_position("AAPL")

# ❌ NEVER: close_all_positions() - nuclear option affecting all bots
client.close_all_positions()

# ❌ NEVER: Record position before confirming fill
order = client.buy(symbol, notional=1000, wait_for_fill=False)
tracker.record_buy(symbol, 10, 100, order["client_order_id"])  # WRONG! Don't know qty yet

# ❌ NEVER: Assume order filled immediately
order = client.submit_order(request)
tracker.record_buy(symbol, order.qty, order.limit_price, ...)  # WRONG! Not filled yet
```

---

## Step 3: Implement Position Tracking with Atomic File Operations

**CRITICAL**: Use atomic read-modify-write with lock held throughout the entire operation.

The v2 bug: calling `load()` then `save()` releases the lock between operations, allowing another process to modify the file in between. v3 fixes this with a context manager that holds the lock for the entire cycle.

### Required: position_tracker.py

```python
"""
Position tracker with ATOMIC file operations for safe concurrent access.
Tracks only this bot's positions based on tagged orders.

v3: Lock held for entire read-modify-write cycle (fixes race condition).
"""

import json
import fcntl
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Generator
from contextlib import contextmanager


class PositionTracker:
    # Threshold for considering a position "closed" (6 decimal places for fractional shares)
    ZERO_THRESHOLD = 0.000001

    def __init__(self, config_path: str, bot_prefix: str, allocated_capital: float = 100000):
        self.config_path = Path(config_path)
        self.bot_prefix = bot_prefix
        self.allocated_capital = allocated_capital

    def _now_utc(self) -> str:
        """Get current time in UTC ISO format."""
        return datetime.now(timezone.utc).isoformat()

    def _ensure_file_exists(self):
        """
        Create file with initial data if it doesn't exist.
        v3: Uses O_CREAT | O_EXCL for atomic creation to prevent race conditions.
        """
        import os
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Atomic creation - fails if file exists
            fd = os.open(str(self.config_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                initial_data = {
                    "bot_prefix": self.bot_prefix,
                    "allocated_capital": self.allocated_capital,
                    "positions": {},
                    "realized_pnl": 0.0,
                    "last_updated": self._now_utc()
                }
                os.write(fd, json.dumps(initial_data, indent=2).encode())
            finally:
                os.close(fd)
        except FileExistsError:
            # File already exists, which is fine
            pass

    @contextmanager
    def _atomic_update(self) -> Generator[dict, None, None]:
        """
        Context manager for atomic file operations.
        Lock is held for the ENTIRE read-modify-write cycle.

        Usage:
            with self._atomic_update() as data:
                data["positions"]["AAPL"] = {...}
                # File is automatically saved on exit
        """
        self._ensure_file_exists()

        with open(self.config_path, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock
            try:
                data = json.load(f)
                yield data  # Caller modifies data
                # Write back with updated timestamp
                data["last_updated"] = self._now_utc()
                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _atomic_read(self) -> Generator[dict, None, None]:
        """
        Context manager for atomic read operations.
        Uses shared lock for concurrent reads.
        """
        self._ensure_file_exists()

        with open(self.config_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock
            try:
                data = json.load(f)
                yield data
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def record_buy(self, symbol: str, qty: float, price: float, order_id: str):
        """
        Record a buy AFTER confirming the fill.

        Args:
            symbol: Stock ticker
            qty: ACTUAL filled quantity (not requested)
            price: ACTUAL fill price (not limit price)
            order_id: The client_order_id for this order
        """
        if qty <= 0:
            return  # Nothing to record

        # Verify order belongs to us
        if not order_id.startswith(f"{self.bot_prefix}-"):
            raise ValueError(f"Order {order_id} doesn't match bot prefix {self.bot_prefix}")

        with self._atomic_update() as data:
            positions = data.setdefault("positions", {})

            if symbol in positions:
                pos = positions[symbol]
                old_qty = pos["qty"]
                old_cost = pos["cost_basis"]
                new_qty = old_qty + qty
                new_cost = old_cost + (qty * price)
                pos["qty"] = new_qty
                pos["cost_basis"] = new_cost
                pos["avg_price"] = new_cost / new_qty
            else:
                positions[symbol] = {
                    "qty": qty,
                    "cost_basis": qty * price,
                    "avg_price": price,
                    "first_bought": self._now_utc(),
                }

            positions[symbol]["last_order_id"] = order_id

    def record_sell(self, symbol: str, qty: float, price: float, order_id: str) -> float:
        """
        Record a sell AFTER confirming the fill.

        Args:
            symbol: Stock ticker
            qty: ACTUAL filled quantity
            price: ACTUAL fill price
            order_id: The client_order_id for this order

        Returns:
            Realized P&L from this sale

        Raises:
            ValueError if we don't own the symbol or don't have enough shares
        """
        if qty <= 0:
            return 0.0

        # Verify order belongs to us
        if not order_id.startswith(f"{self.bot_prefix}-"):
            raise ValueError(f"Order {order_id} doesn't match bot prefix {self.bot_prefix}")

        with self._atomic_update() as data:
            positions = data.setdefault("positions", {})

            if symbol not in positions:
                raise ValueError(f"BLOCKED: Cannot sell {symbol} - not in our positions! "
                               f"This may belong to another bot.")

            pos = positions[symbol]
            if qty > pos["qty"] + self.ZERO_THRESHOLD:
                raise ValueError(f"BLOCKED: Cannot sell {qty} of {symbol} - only own {pos['qty']}")

            # Calculate realized P&L
            avg_cost = pos["avg_price"]
            realized = (price - avg_cost) * qty
            data["realized_pnl"] = data.get("realized_pnl", 0.0) + realized

            # Update position
            pos["qty"] -= qty
            pos["cost_basis"] -= (avg_cost * qty)

            # Remove if effectively zero
            if pos["qty"] < self.ZERO_THRESHOLD:
                del positions[symbol]
            else:
                pos["last_order_id"] = order_id

            return realized

    def get_position(self, symbol: str) -> Optional[dict]:
        """Get position for a symbol, or None if not owned."""
        with self._atomic_read() as data:
            return data.get("positions", {}).get(symbol)

    def owns(self, symbol: str) -> bool:
        """Check if we own any shares of this symbol."""
        with self._atomic_read() as data:
            return symbol in data.get("positions", {})

    def get_qty(self, symbol: str) -> float:
        """Get quantity owned, or 0 if not owned."""
        pos = self.get_position(symbol)
        return pos["qty"] if pos else 0.0

    @property
    def total_cost_basis(self) -> float:
        """Total cost basis of all positions."""
        with self._atomic_read() as data:
            return sum(p["cost_basis"] for p in data.get("positions", {}).values())

    @property
    def realized_pnl(self) -> float:
        """Total realized P&L."""
        with self._atomic_read() as data:
            return data.get("realized_pnl", 0.0)

    @property
    def cash_available(self) -> float:
        """Virtual cash = allocation + realized P&L - cost basis of positions."""
        with self._atomic_read() as data:
            realized = data.get("realized_pnl", 0.0)
            cost_basis = sum(p["cost_basis"] for p in data.get("positions", {}).values())
            return max(0, self.allocated_capital + realized - cost_basis)

    def get_all_positions(self) -> dict:
        """Get all positions (atomic read)."""
        with self._atomic_read() as data:
            return data.get("positions", {}).copy()
```

---

## Step 4: Safe Trading Functions

### Pattern: Always Wait for Fill Before Recording

```python
def safe_buy(tracker: PositionTracker, client: AlpacaClient,
             symbol: str, notional: float) -> dict:
    """
    Safely buy shares with proper tracking.

    1. Checks virtual cash
    2. Submits tagged order
    3. Waits for fill
    4. Records ACTUAL fill (not requested amount)
    5. Handles partial fills properly (v3)
    """
    # Check virtual cash
    if notional > tracker.cash_available:
        raise ValueError(
            f"Insufficient virtual funds: want ${notional:.2f}, "
            f"have ${tracker.cash_available:.2f}"
        )

    # Submit and wait for fill
    result = client.buy(symbol, notional=notional, wait_for_fill=True)

    if result["status"] != "filled":
        # v3: Handle partial fills - record what DID fill before raising
        if result["filled_qty"] > 0:
            tracker.record_buy(
                symbol=symbol,
                qty=result["filled_qty"],
                price=result["filled_avg_price"],
                order_id=result["client_order_id"]
            )
        raise ValueError(f"Order not fully filled: {result['status']}, "
                        f"filled {result['filled_qty']} of requested ${notional:.2f}")

    # Record ACTUAL fill quantities
    tracker.record_buy(
        symbol=symbol,
        qty=result["filled_qty"],
        price=result["filled_avg_price"],
        order_id=result["client_order_id"]
    )

    return result


def safe_sell(tracker: PositionTracker, client: AlpacaClient,
              symbol: str, qty: float) -> dict:
    """
    Safely sell shares with ownership verification.

    1. Verifies we own the symbol
    2. Verifies we own enough shares
    3. Submits tagged order for EXACT quantity
    4. Waits for fill
    5. Records ACTUAL fill
    """
    # Ownership check
    if not tracker.owns(symbol):
        raise ValueError(
            f"BLOCKED: {symbol} not in our positions. "
            f"May belong to another bot - DO NOT SELL!"
        )

    # Quantity check
    our_qty = tracker.get_qty(symbol)
    if qty > our_qty:
        raise ValueError(
            f"BLOCKED: Cannot sell {qty} of {symbol}, only own {our_qty}"
        )

    # Submit and wait for fill
    result = client.sell(symbol, qty=qty, wait_for_fill=True)

    if result["status"] != "filled":
        # Handle partial fills
        if result["filled_qty"] > 0:
            tracker.record_sell(
                symbol=symbol,
                qty=result["filled_qty"],
                price=result["filled_avg_price"],
                order_id=result["client_order_id"]
            )
        raise ValueError(f"Order not fully filled: {result['status']}, "
                        f"filled {result['filled_qty']} of {qty}")

    # Record ACTUAL fill
    realized_pnl = tracker.record_sell(
        symbol=symbol,
        qty=result["filled_qty"],
        price=result["filled_avg_price"],
        order_id=result["client_order_id"]
    )

    result["realized_pnl"] = realized_pnl
    return result
```

---

## Step 5: Directory Structure

```
~/your-bot-name/
├── config/
│   └── positions.json     # Auto-generated position tracking
├── logs/
│   ├── bot.log           # Operational logs
│   └── trades.json       # Complete trade history (backup)
├── src/
│   ├── __init__.py
│   ├── alpaca_client.py  # From Step 2
│   ├── position_tracker.py  # From Step 3
│   ├── strategy.py       # Your strategy logic
│   └── main.py           # Entry point
├── requirements.txt
└── README.md
```

### Required: Trade History Backup (with atomic file operations)

In addition to positions.json, maintain a complete trade log for recovery.
**v3**: Uses atomic read-modify-write with lock held throughout.

```python
import fcntl
from pathlib import Path
from datetime import datetime, timezone

def log_trade(trade_result: dict, log_path: str = "logs/trades.json"):
    """
    Append trade to history log for recovery purposes.
    Uses atomic file operations with locking.
    """
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    trade_result["logged_at"] = datetime.now(timezone.utc).isoformat()

    if log_file.exists():
        # Atomic read-modify-write
        with open(log_file, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                trades = json.load(f)
                trades.append(trade_result)
                f.seek(0)
                f.truncate()
                json.dump(trades, f, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    else:
        # Create new file
        with open(log_file, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump([trade_result], f, indent=2)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

---

## Step 6: Verification Checklist

Before deploying, verify ALL items:

### Prefix Registration
- [ ] Prefix is 2-4 uppercase characters
- [ ] Prefix is registered in `~/.config/personal-os/alpaca-bot-registry.json`
- [ ] Prefix does NOT match any existing bot
- [ ] Registration uses file locking (v3)

### Order Tagging
- [ ] `BOT_PREFIX` constant is set (no trailing dash)
- [ ] `_generate_order_id()` produces `{PREFIX}-{uuid}` format
- [ ] ALL buy orders include `client_order_id`
- [ ] ALL sell orders include `client_order_id`
- [ ] `wait_for_fill()` is called before recording positions
- [ ] `_status_str()` used for status comparisons (v3)

### Position Tracking
- [ ] positions.json uses `_atomic_update()` context manager (v3)
- [ ] `record_buy()` uses ACTUAL filled qty/price
- [ ] `record_buy()` validates order prefix matches tracker (v3)
- [ ] `record_sell()` checks ownership BEFORE submitting order
- [ ] `record_sell()` uses ACTUAL filled qty/price
- [ ] `record_sell()` validates order prefix matches tracker (v3)
- [ ] ZERO_THRESHOLD handles fractional shares (6 decimals)

### Safety
- [ ] Code NEVER uses `close_position()` API
- [ ] Code NEVER uses `close_all_positions()` API
- [ ] Code NEVER records position before fill confirmation
- [ ] Sell logic caps quantity to what we actually own

### Recovery (v3)
- [ ] Trade history logged with atomic file locking
- [ ] Trade logs include `partial_fill` flag and `symbol`/`side` fields
- [ ] Recovery functions handle partial fills (filled_qty > 0)
- [ ] `reconcile_positions()` available to verify state after recovery

---

## Step 7: Testing

Run these tests before enabling live trading:

```python
import unittest
from alpaca_client import AlpacaClient
from position_tracker import PositionTracker
import tempfile
import os

class TestBotSegregation(unittest.TestCase):

    def test_order_id_format(self):
        """Order IDs must have correct prefix format."""
        client = AlpacaClient(paper=True)
        order_id = client._generate_order_id()

        self.assertTrue(order_id.startswith(f"{client.BOT_PREFIX}-"))
        self.assertGreater(len(order_id), len(client.BOT_PREFIX) + 1)

    def test_ownership_detection(self):
        """Must correctly identify own vs other bots' orders."""
        client = AlpacaClient(paper=True)

        own_order = f"{client.BOT_PREFIX}-abc123"
        self.assertTrue(client.is_our_order(own_order))

        # Other bots' orders
        self.assertFalse(client.is_our_order("HF-abc123"))
        self.assertFalse(client.is_our_order("MOM-xyz789"))
        self.assertFalse(client.is_our_order(None))
        self.assertFalse(client.is_our_order(""))
        self.assertFalse(client.is_our_order("random"))

    def test_cannot_sell_unowned(self):
        """Must block sells of positions we don't own."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tracker = PositionTracker(f.name, "TEST", 100000)

        try:
            with self.assertRaises(ValueError) as ctx:
                tracker.record_sell("FAKE", 10, 100.0, "TEST-sell1")
            self.assertIn("not in our positions", str(ctx.exception))
        finally:
            os.unlink(f.name)

    def test_cannot_oversell(self):
        """Must block selling more than we own."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tracker = PositionTracker(f.name, "TEST", 100000)

        try:
            tracker.record_buy("TEST", 5, 100.0, "TEST-buy1")

            with self.assertRaises(ValueError) as ctx:
                tracker.record_sell("TEST", 10, 100.0, "TEST-sell1")
            self.assertIn("only own", str(ctx.exception))
        finally:
            os.unlink(f.name)

    def test_cash_tracking(self):
        """Virtual cash must track correctly."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tracker = PositionTracker(f.name, "TEST", 100000)

        try:
            self.assertEqual(tracker.cash_available, 100000)

            tracker.record_buy("AAPL", 10, 150.0, "TEST-buy1")  # $1500
            self.assertEqual(tracker.cash_available, 98500)

            # Sell at profit
            tracker.record_sell("AAPL", 10, 160.0, "TEST-sell1")  # +$100 P&L
            self.assertEqual(tracker.cash_available, 100100)
        finally:
            os.unlink(f.name)

    def test_partial_position_sell(self):
        """Must handle selling part of a position."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tracker = PositionTracker(f.name, "TEST", 100000)

        try:
            tracker.record_buy("AAPL", 10, 100.0, "TEST-buy1")
            tracker.record_sell("AAPL", 3, 110.0, "TEST-sell1")

            self.assertEqual(tracker.get_qty("AAPL"), 7)
            self.assertTrue(tracker.owns("AAPL"))
        finally:
            os.unlink(f.name)

    def test_fractional_shares(self):
        """Must handle fractional shares correctly."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            tracker = PositionTracker(f.name, "TEST", 100000)

        try:
            tracker.record_buy("AAPL", 0.5, 100.0, "TEST-buy1")
            self.assertEqual(tracker.get_qty("AAPL"), 0.5)

            tracker.record_sell("AAPL", 0.5, 100.0, "TEST-sell1")
            self.assertFalse(tracker.owns("AAPL"))  # Should be removed
        finally:
            os.unlink(f.name)

if __name__ == "__main__":
    unittest.main()
```

---

## Step 8: Recovery Procedure

If positions.json gets corrupted or lost:

### Option 1: Rebuild from Trade Log (handles partial fills)

```python
def rebuild_from_trade_log(log_path: str, tracker: PositionTracker):
    """
    Rebuild positions from trades.json backup.
    v3: Handles partial fills and timeout states.
    """
    trades = json.loads(Path(log_path).read_text())

    # Reset tracker by writing directly (atomic)
    with tracker._atomic_update() as data:
        data["positions"] = {}
        data["realized_pnl"] = 0.0

    for trade in trades:
        if not trade.get("client_order_id", "").startswith(f"{tracker.bot_prefix}-"):
            continue  # Skip other bots' trades

        status = trade.get("status", "")
        filled_qty = trade.get("filled_qty", 0)
        filled_price = trade.get("filled_avg_price", 0)

        # v3: Include partial fills (status may be "timeout_partially_filled" or "canceled" with filled_qty > 0)
        if filled_qty <= 0:
            continue

        # Check if we should include this trade
        # Full fills: status == "filled"
        # Partial fills: partial_fill flag is True, or filled_qty > 0 with non-filled status
        is_valid_fill = (
            status == "filled" or
            trade.get("partial_fill", False) or
            (status.startswith("timeout_") and filled_qty > 0) or
            (status in ["canceled", "expired"] and filled_qty > 0)
        )

        if not is_valid_fill:
            continue

        side = trade.get("side", "").lower()
        symbol = trade.get("symbol")

        if side == "buy":
            tracker.record_buy(symbol, filled_qty, filled_price, trade["client_order_id"])
        elif side == "sell":
            try:
                tracker.record_sell(symbol, filled_qty, filled_price, trade["client_order_id"])
            except ValueError:
                pass  # Position already closed
```

### Option 2: Rebuild from Alpaca Orders (handles partial fills)

```python
def rebuild_from_alpaca(client: AlpacaClient, tracker: PositionTracker):
    """
    Rebuild positions from Alpaca order history.
    v3: Handles partial fills.

    WARNING: Alpaca may only retain 90 days / 500 orders.
    Use trade log backup for older history.
    """
    orders = client.get_our_orders(status="closed", limit=500)

    # Sort by filled_at timestamp
    orders.sort(key=lambda o: o.filled_at or o.submitted_at)

    # Reset tracker by writing directly (atomic)
    with tracker._atomic_update() as data:
        data["positions"] = {}
        data["realized_pnl"] = 0.0

    for order in orders:
        # v3: Include orders with any filled quantity (not just fully filled)
        filled_qty = float(order.filled_qty) if order.filled_qty else 0
        if filled_qty <= 0:
            continue

        filled_price = float(order.filled_avg_price) if order.filled_avg_price else 0
        side = client._status_str(order.side)

        if side == "buy":
            tracker.record_buy(order.symbol, filled_qty, filled_price, order.client_order_id)
        elif side == "sell":
            try:
                tracker.record_sell(order.symbol, filled_qty, filled_price, order.client_order_id)
            except ValueError:
                pass  # Position already closed
```

### Option 3: Reconcile Local vs Alpaca (recommended after recovery)

```python
def reconcile_positions(client: AlpacaClient, tracker: PositionTracker):
    """
    Verify local positions match Alpaca's view of our orders.
    Returns discrepancies for manual review.
    """
    # Get all our filled orders
    orders = client.get_our_orders(status="closed", limit=500)

    # Calculate positions from orders
    alpaca_positions = {}
    for order in orders:
        filled_qty = float(order.filled_qty) if order.filled_qty else 0
        if filled_qty <= 0:
            continue

        symbol = order.symbol
        side = client._status_str(order.side)
        filled_price = float(order.filled_avg_price) if order.filled_avg_price else 0

        if symbol not in alpaca_positions:
            alpaca_positions[symbol] = {"qty": 0, "cost_basis": 0}

        if side == "buy":
            alpaca_positions[symbol]["qty"] += filled_qty
            alpaca_positions[symbol]["cost_basis"] += filled_qty * filled_price
        elif side == "sell":
            alpaca_positions[symbol]["qty"] -= filled_qty
            # Note: cost basis on sells handled differently, skip for simplicity

    # Compare with local
    local_positions = tracker.get_all_positions()
    discrepancies = []

    all_symbols = set(alpaca_positions.keys()) | set(local_positions.keys())
    for symbol in all_symbols:
        alpaca_qty = alpaca_positions.get(symbol, {}).get("qty", 0)
        local_qty = local_positions.get(symbol, {}).get("qty", 0)

        # Use ZERO_THRESHOLD for comparison
        if abs(alpaca_qty - local_qty) > tracker.ZERO_THRESHOLD:
            discrepancies.append({
                "symbol": symbol,
                "local_qty": local_qty,
                "alpaca_qty": alpaca_qty,
                "diff": alpaca_qty - local_qty
            })

    return discrepancies
```

---

## Common Mistakes to Avoid

| Mistake | Why It's Dangerous | Correct Approach |
|---------|-------------------|------------------|
| Using `close_position()` | Closes ALL shares including other bots' | Use `sell()` with exact qty |
| Recording before fill | Order may not fill, or fill different qty | Wait for fill, use actual qty |
| No prefix in order ID | Can't identify ownership | Always use `_generate_order_id()` |
| Querying Alpaca positions directly | Returns all bots' positions | Use your position tracker |
| Load-then-save file locking | Race condition between operations | Use `_atomic_update()` context manager |
| Not logging trades | Can't recover if positions.json lost | Log every trade with atomic locking |
| Assuming immediate fills | Market orders can be delayed/partial | Always `wait_for_fill()` |
| Ignoring partial fills | Lost position data if order times out | Check `partial_fill` flag, log filled_qty |
| String status comparison | Alpaca may return enum or string | Use `_status_str()` normalizer |
| Mismatched prefix | Client and tracker use different prefixes | Validate in `record_buy/sell` |

---

## v3 Changes Summary

This version (v3) addresses race conditions and edge cases found during iterative red team testing:

1. **Atomic file operations**: Lock held for entire read-modify-write cycle via `_atomic_update()` context manager
2. **Atomic file creation**: Uses `O_CREAT | O_EXCL` to prevent race conditions during file initialization
3. **Registry locking**: Bot registration uses file locking to prevent collisions
4. **Order status normalization**: `_status_str()` handles enum vs string comparison
5. **Partial fill handling**: Both `safe_buy()` and `safe_sell()` record partial fills before raising exceptions
6. **Network error retry**: `wait_for_fill()` includes exponential backoff and `needs_reconciliation` flag
7. **Prefix validation**: `record_buy/sell` verify order ID matches tracker's bot prefix
8. **Reconciliation tool**: `reconcile_positions()` to verify local vs Alpaca state after recovery

---

## Known Limitations

These are documented limitations of v3 that are acceptable for paper trading:

### Concurrent Same-Symbol Operations
If two processes simultaneously sell the same symbol, both may pass ownership checks before either records. The second order could result in overselling.

**Mitigation:** For paper trading, this is rare. For production, implement per-symbol locking:
```python
def lock_symbol(self, symbol: str):
    """Acquire per-symbol lock file."""
    lock_path = self.config_path.parent / f".{symbol}.lock"
    ...
```

### Alpaca 90-Day Order History Limit
Alpaca only retains ~90 days / 500 orders. Recovery from Alpaca orders may miss older trades.

**Mitigation:** Always maintain the trade log backup and use it as primary recovery source.

### Post-Timeout Order Fills
If an order fills after `wait_for_fill()` times out, the position may not be recorded.

**Mitigation:** The `needs_reconciliation` flag signals when to run `reconcile_positions()` before the next trade.
