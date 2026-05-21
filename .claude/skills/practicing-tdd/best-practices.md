# Testing Best Practices - Quick Reference

This document summarizes the critical testing rules that must be followed in this project.

## The Five Golden Rules

### 1. Reuse Before Creating ♻️

**Before creating ANY new test fixture or factory:**

```python
# Step 1: Check conftest.py for existing fixtures
# Available fixtures:
# - test_database (temporary SQLite DB)
# - mock_alpaca_service (mocked broker API)
# - sample_position, sample_trade, sample_quote (test data)

# Step 2: Check tests/factories.py for data factories
# Available factories:
# - create_polygon_trade() - Polygon-compliant trade data
# - create_polygon_quote() - Polygon-compliant quote data
# - create_bar_data() - OHLCV bar data

# Step 3: Ask yourself
# - Can I reuse an existing fixture?
# - Can I extend a fixture with parameters?
# - Can I use a factory with custom args?

# ❌ WRONG - Creating duplicate
@pytest.fixture
def my_database():
    return SQLAlchemyAdapter("test.db")

# ✅ RIGHT - Reusing existing
async def test_feature(test_database):
    # Use the existing test_database fixture
    pass

# ✅ RIGHT - Extending factory
from tests.factories import create_polygon_trade

trade = create_polygon_trade(price=250.0, size=100)
```

**Why it matters**: Prevents test fixture sprawl, ensures consistency, reduces maintenance burden.

---

### 2. Check Coverage First 📊

**Before writing ANY new test:**

```bash
# Run coverage report
make test

# Output shows:
# - Percentage covered per file
# - Specific lines not covered
# - Branches not tested

# Focus new tests on:
# 1. Untested lines/functions
# 2. Missing edge cases
# 3. Uncovered error paths
```

**Coverage report example:**
```
trading/services/prediction.py    87%    Lines 45-52 not covered
tests/test_prediction.py          95%    Missing edge case tests
```

**Action**: Write tests for lines 45-52, not for already-covered code.

**Why it matters**: Prevents redundant tests, maximizes value of new tests, identifies real gaps.

---

### 3. Parametrize for Maintainability 🔄

**When testing multiple similar scenarios:**

```python
# ❌ WRONG - Repetitive test functions
async def test_valid_input():
    result = process("valid")
    assert result.success is True

async def test_empty_input():
    result = process("")
    assert result.success is False

async def test_none_input():
    with pytest.raises(ValueError):
        process(None)

# ✅ RIGHT - Parametrized test
@pytest.mark.parametrize("input,expected,should_raise", [
    ("valid", True, None),
    ("", False, None),
    (None, None, ValueError),
])
async def test_various_inputs(input, expected, should_raise):
    if should_raise:
        with pytest.raises(should_raise):
            process(input)
    else:
        result = process(input)
        assert result.success == expected
```

**Benefits**:
- Single test function for multiple scenarios
- Easy to add new test cases (just add to list)
- Clear test data in one place
- Reduces code duplication

**Why it matters**: Easier to maintain, scales better, clearer test intent.

---

### 4. NO Imports Inside Functions 🚫

**NEVER import inside function bodies** (except documented circular imports):

```python
# ❌ WRONG - Import inside function
def my_function():
    from trading.services import SomeService  # FORBIDDEN!
    service = SomeService()

# ❌ WRONG - Import inside test
def test_feature():
    from trading.bots import SingleAssetBot  # FORBIDDEN!
    bot = SingleAssetBot()

# ✅ RIGHT - Top-level import
from trading.services import SomeService

def my_function():
    service = SomeService()

# ⚠️ ONLY IF CIRCULAR IMPORT (must document!)
def my_function():
    # TODO: Fix circular import between trading.services and trading.bots
    # Circular dependency: SomeService imports Bot, Bot imports SomeService
    from trading.services import SomeService
    service = SomeService()
```

**Why it's forbidden**:
- Hides dependencies (makes code harder to understand)
- Slows down function execution
- Makes refactoring harder
- Often indicates design problems

**Exception**: Circular imports (must be documented with TODO for humans to fix).

**Why it matters**: Code clarity, performance, maintainability, reveals design issues.

---

### 5. Database Testing Strategy 🗄️

**Choose the right database approach:**

```python
# ✅ Use REAL database for:
# - Integration tests
# - Database adapter tests
# - SQLAlchemy query validation
# - Testing transactions/rollbacks
# - Testing database relationships

@pytest.mark.asyncio
async def test_position_creation_integration(test_database):
    """Integration test - uses real DB"""
    position = await test_database.create_position(
        symbol="TSLA",
        entry_price=250.0
    )

    # Validates actual SQL execution
    assert position.id is not None

    # Test database relationships
    trades = await test_database.get_trades_for_position(position.id)
    assert len(trades) == 0

# ✅ MOCK database for:
# - Unit tests of business logic
# - Testing algorithm/calculation logic
# - When DB is incidental to test

from unittest.mock import MagicMock, AsyncMock

@pytest.mark.asyncio
async def test_profit_calculation_unit():
    """Unit test - mocks DB"""
    mock_db = MagicMock()
    mock_db.get_current_position = AsyncMock(return_value=MagicMock(
        entry_price=100.0,
        quantity=50
    ))

    bot = SingleAssetBot(db=mock_db, profit_taking=0.01)

    # Testing calculation logic, not DB behavior
    profit_price = bot.calculate_profit_target()
    assert profit_price == 101.0  # 100.0 * (1 + 0.01)
```

**Decision Tree**:
```
Are you testing...
├─ SQL queries / transactions / relationships?
│  └─ Use REAL database (test_database fixture)
│
├─ Database adapter methods?
│  └─ Use REAL database (test_database fixture)
│
└─ Business logic that happens to use DB?
   └─ MOCK database (focus on logic, not DB)
```

**Why it matters**:
- Real DB: Catches SQL bugs, validates actual database behavior
- Mock DB: Fast unit tests, isolates business logic

---

## Quick Checklist for Writing Tests

Before writing a test, answer these questions:

- [ ] Can I reuse an existing fixture from `conftest.py`?
- [ ] Can I use a factory from `tests/factories.py`?
- [ ] Have I run `make test` to check current coverage?
- [ ] Am I testing something not already covered?
- [ ] Can I parametrize this test for multiple scenarios?
- [ ] Are all my imports at the top of the file?
- [ ] Should I use real DB or mock DB for this test?

---

## Common Violations and Fixes

### Violation: Creating Duplicate Fixtures

```python
# ❌ WRONG
@pytest.fixture
def database():
    return SQLAlchemyAdapter("test.db")

@pytest.fixture
def db_connection():
    return SQLAlchemyAdapter("another.db")

# ✅ RIGHT - Use existing test_database from conftest.py
async def test_my_feature(test_database):
    pass
```

### Violation: Not Checking Coverage

```python
# ❌ WRONG - Writing test without checking coverage
def test_calculate_profit():
    # This might already be tested!
    assert calculate_profit(100, 0.1) == 110

# ✅ RIGHT - Check coverage first
# 1. Run: make test
# 2. See: calculate_profit is 100% covered
# 3. Write test for uncovered edge case instead
def test_calculate_profit_with_negative_margin():
    # This edge case wasn't covered
    with pytest.raises(ValueError):
        calculate_profit(100, -0.1)
```

### Violation: Repetitive Tests

```python
# ❌ WRONG - Separate test for each input
def test_process_valid():
    assert process("valid") == True

def test_process_empty():
    assert process("") == False

def test_process_none():
    with pytest.raises(ValueError):
        process(None)

# ✅ RIGHT - Parametrized
@pytest.mark.parametrize("input,expected", [
    ("valid", True),
    ("", False),
    (None, ValueError),
])
def test_process(input, expected):
    if expected == ValueError:
        with pytest.raises(ValueError):
            process(input)
    else:
        assert process(input) == expected
```

### Violation: Imports Inside Functions

```python
# ❌ WRONG
def calculate_total():
    from trading.utils import math_helpers
    return math_helpers.sum([1, 2, 3])

# ✅ RIGHT
from trading.utils import math_helpers

def calculate_total():
    return math_helpers.sum([1, 2, 3])
```

### Violation: Wrong Database Strategy

```python
# ❌ WRONG - Using real DB for unit test of calculation logic
async def test_profit_calculation(test_database):
    position = await test_database.create_position(...)
    # Just testing math, don't need real DB!
    profit = calculate_profit(position.entry_price, 0.01)
    assert profit == expected

# ✅ RIGHT - Mock for unit test
def test_profit_calculation():
    entry_price = 100.0
    profit_margin = 0.01
    profit = calculate_profit(entry_price, profit_margin)
    assert profit == 101.0

# ✅ RIGHT - Real DB for integration test
async def test_position_profit_integration(test_database):
    position = await test_database.create_position(
        entry_price=100.0
    )
    # Testing actual DB retrieval + calculation
    current_profit = await calculate_position_profit(
        test_database,
        position.id
    )
    assert current_profit is not None
```

---

## Available Test Utilities

### From `conftest.py`:

```python
# Database fixture (real SQLite)
async def test_feature(test_database):
    position = await test_database.create_position(...)

# Mocked Alpaca service
async def test_trading(mock_alpaca_service):
    mock_alpaca_service.buy.return_value = OrderResponse(...)

# Sample test data
def test_with_sample_data(sample_position, sample_trade):
    assert sample_position.id is not None
```

### From `tests/factories.py`:

```python
from tests.factories import (
    create_polygon_trade,
    create_polygon_quote,
    create_bar_data,
)

# Create Polygon-compliant trade
trade = create_polygon_trade(
    price=250.0,
    size=100,
    conditions=[12],  # Regular sale
)

# Create quote
quote = create_polygon_quote(
    bid_price=249.95,
    ask_price=250.05,
)

# Create OHLCV bar
bar = create_bar_data(
    symbol="TSLA",
    open=250.0,
    high=255.0,
    low=248.0,
    close=253.0,
    volume=10000,
)
```

---

## Testing Workflow

### Step-by-Step Process:

1. **Check existing tests**:
   ```bash
   make test
   # Review coverage report
   ```

2. **Identify what to test**:
   - Look for uncovered lines
   - Identify missing edge cases
   - Find untested error paths

3. **Check for reusable fixtures**:
   - Review `conftest.py`
   - Review `tests/factories.py`
   - Can existing utilities be reused?

4. **Decide on database strategy**:
   - Testing DB behavior? → Real DB
   - Testing business logic? → Mock DB

5. **Write test**:
   - Use parametrize for multiple scenarios
   - Keep imports at top of file
   - Reuse existing fixtures/factories

6. **Verify coverage improved**:
   ```bash
   make test
   # Check that coverage increased in target areas
   ```

---

## Summary

**The Five Golden Rules**:
1. ♻️ Reuse before creating (fixtures/factories)
2. 📊 Check coverage first (`make test`)
3. 🔄 Parametrize for maintainability
4. 🚫 NO imports inside functions
5. 🗄️ Real DB for integration, mock for unit

**Follow these rules and your tests will be**:
- Maintainable
- Efficient
- Non-redundant
- Fast
- Reliable

**Violate these rules and you'll have**:
- Duplicate fixtures
- Redundant tests
- Slow test suites
- Hidden dependencies
- Maintenance nightmares
