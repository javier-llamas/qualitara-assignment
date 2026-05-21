---
name: practicing-tdd
description: Practicing Test-Driven Development for implementing new trading bot features. Use when writing tests first, implementing code to pass tests, or following the Red-Green-Refactor cycle. Enforces strict phase separation between writing tests and implementation.
---

# Test-Driven Development (TDD) Implementation Guide

## Overview

This project enforces **strict Test-Driven Development** for all new features. This guide explains the methodology and how it's enforced in implementation plans.

## Quick Reference

**Essential Commands:**
- `make test` - Run tests with coverage report (uses `uv run pytest`)
- `uv run pytest tests/test_[feature].py -v` - Run specific test file
- `uv run pytest -k "test_name" -v` - Run test by name pattern
- `make mypy` - Type checking
- `make black` - Code formatting

**Key Files:**
- Test fixtures: `tests/conftest.py` (34+ fixtures available)
- Test factories: `tests/factories.py` (Polygon-compliant test data)
- Best practices: `.claude/skills/practicing-tdd/best-practices.md`

## Core TDD Principles

### The Three Phases

Every new feature must follow this exact sequence:

```
Phase 1: Write Failing Tests
    ↓
Phase 2: Implement Code (Make Tests Pass)
    ↓
Phase 3: Refactor (Optional)
```

### Phase Separation Rules

**CRITICAL**: Each phase has strict boundaries:

| Phase | Allowed | Forbidden |
|-------|---------|-----------|
| **Phase 1: Tests** | Write test files, fixtures, test utilities | Write ANY implementation code |
| **Phase 2: Implementation** | Write implementation code only | Modify tests (unless test has bugs) |
| **Phase 3: Refactor** | Improve code structure, performance | Modify tests, change behavior |

## Phase 1: Write Failing Tests

### Goals
- Define feature behavior through tests
- Document expected API/interface
- Cover edge cases and error conditions
- All tests should FAIL (feature doesn't exist yet)

### What to Create

#### Unit Tests (`tests/test_[feature].py`)
```python
import pytest
from trading.services.new_service import NewService

@pytest.mark.asyncio
async def test_new_service_success_case():
    """Test successful execution"""
    service = NewService(param="value")
    result = await service.process()

    assert result.success is True
    assert result.data == expected_output

@pytest.mark.asyncio
async def test_new_service_handles_invalid_input():
    """Test error handling"""
    service = NewService(param=None)

    with pytest.raises(ValueError, match="param cannot be None"):
        await service.process()

@pytest.mark.asyncio
async def test_new_service_with_edge_case():
    """Test boundary conditions"""
    service = NewService(param="")
    result = await service.process()

    assert result.success is False
    assert "empty" in result.error_message.lower()
```

#### Integration Tests (`tests/integration/test_[feature]_integration.py`)
```python
@pytest.mark.asyncio
async def test_new_service_with_database(test_database):
    """Test service with real database"""
    service = NewService(db=test_database, param="value")
    result = await service.process()

    # Verify database state
    records = await test_database.get_records()
    assert len(records) == 1
    assert records[0].status == "processed"

@pytest.mark.asyncio
async def test_new_service_with_mocked_api(mock_alpaca_service):
    """Test service with mocked external API"""
    service = NewService(broker=mock_alpaca_service)
    result = await service.process()

    mock_alpaca_service.some_method.assert_called_once()
```

### Test Fixtures (in `conftest.py`)
```python
@pytest.fixture
async def new_service_config():
    """Provide test configuration for new service"""
    return {
        "param1": "test_value",
        "param2": 100,
        "enable_feature": True
    }

@pytest.fixture
async def sample_service_data():
    """Provide sample data for testing"""
    return ServiceData(
        id=1,
        name="test",
        value=42.0
    )
```

### Success Criteria

✅ **Must Have**:
- All tests execute: `pytest tests/test_[feature].py -v`
- All tests FAIL (expected since feature not implemented)
- Tests follow pytest conventions
- Test names clearly describe what they test
- Proper use of fixtures and async patterns
- No syntax errors: `make mypy`

❌ **Must NOT Have**:
- Any implementation code
- Import statements for non-existent modules (tests can import what will be created)

### Phase 1 Checklist

- [ ] Unit tests cover happy path
- [ ] Unit tests cover error conditions
- [ ] Unit tests cover edge cases
- [ ] Integration tests cover system interactions
- [ ] Test fixtures created/updated in conftest.py
- [ ] All tests execute and fail as expected
- [ ] Tests are reviewed and approved by human

## Phase 2: Implement Code

### Goals
- Write minimal code to make ALL tests pass
- Follow existing codebase patterns
- Do NOT modify tests (unless they have bugs)

### What to Create

#### Core Implementation
```python
# trading/services/new_service.py
from typing import Optional
from dataclasses import dataclass

@dataclass
class ServiceResult:
    success: bool
    data: Optional[dict] = None
    error_message: Optional[str] = None

class NewService:
    def __init__(self, param: Optional[str]):
        if param is None:
            raise ValueError("param cannot be None")

        self.param = param

    async def process(self) -> ServiceResult:
        """Process service request"""
        if self.param == "":
            return ServiceResult(
                success=False,
                error_message="param is empty"
            )

        # Implementation logic
        result_data = {"output": f"processed_{self.param}"}

        return ServiceResult(
            success=True,
            data=result_data
        )
```

#### Integration Points
```python
# trading/bots/single_asset_bot.py (updates)
from trading.services.new_service import NewService

async def on_bar(self, bar_data):
    # Existing code...

    # Use new service
    service = NewService(param=self.config.param)
    result = await service.process()

    if result.success:
        logger.info(f"Service processed: {result.data}")
    else:
        logger.error(f"Service failed: {result.error_message}")
```

### Success Criteria

✅ **Must Have**:
- All tests pass: `make test`
- Type checking passes: `make mypy`
- Linting passes: `make black` and `make lint`
- Integration tests pass: `pytest tests/integration/ -v`
- Code follows existing patterns (DI, async, logging)

❌ **Must NOT Do**:
- Modify tests to make them pass (tests define the contract!)
- Add functionality not covered by tests
- Skip error handling that tests expect

### Phase 2 Checklist

- [ ] Core implementation created
- [ ] Integration points updated
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Type checking passes
- [ ] Linting passes
- [ ] Manual testing in paper trading successful
- [ ] Code reviewed and approved

## Phase 3: Refactor (Optional)

### Goals
- Improve code quality without changing behavior
- Remove duplication
- Enhance readability
- Optimize performance
- Tests must stay green!

### What to Improve

#### Code Quality
```python
# Before refactoring
async def process(self) -> ServiceResult:
    if self.param == "":
        return ServiceResult(success=False, error_message="param is empty")
    result_data = {"output": f"processed_{self.param}"}
    return ServiceResult(success=True, data=result_data)

# After refactoring - extracted helper
async def process(self) -> ServiceResult:
    if not self._is_valid_param():
        return self._error_result("param is empty")

    data = self._build_result_data()
    return self._success_result(data)

def _is_valid_param(self) -> bool:
    return bool(self.param and self.param.strip())

def _error_result(self, message: str) -> ServiceResult:
    return ServiceResult(success=False, error_message=message)

def _success_result(self, data: dict) -> ServiceResult:
    return ServiceResult(success=True, data=data)

def _build_result_data(self) -> dict:
    return {"output": f"processed_{self.param}"}
```

### Success Criteria

✅ **Must Maintain**:
- All tests still pass: `make test`
- Type checking still passes: `make mypy`
- Same or better performance
- Same or better code coverage

✅ **Improvements**:
- More readable code
- Less duplication
- Better variable/function names
- Clearer separation of concerns

❌ **Must NOT Do**:
- Change test behavior
- Modify test files
- Break existing functionality

### Phase 3 Checklist

- [ ] Code is more readable
- [ ] Duplication removed
- [ ] Helper functions extracted
- [ ] Performance optimized (if needed)
- [ ] All tests still pass
- [ ] No behavior changes
- [ ] Refactoring reviewed and approved

## Enforcing TDD in Implementation Plans

### Plan Structure

Every implementation plan for new features MUST include:

```markdown
## Implementation Approach

**TDD Note**: This plan follows Test-Driven Development:
- Phase 1: Write failing tests (defines behavior)
- Phase 2: Implement code (makes tests pass)
- Phase 3: Refactor (improve while keeping tests green)

## Phase 1: Write Failing Tests (TDD)
[Detailed test specifications]

**CRITICAL**: No implementation code in this phase.

## Phase 2: Implement Feature (TDD)
[Implementation specifications]

**CRITICAL**: No test modifications in this phase.

## Phase 3: Refactor (TDD - Optional)
[Refactoring opportunities]

**CRITICAL**: Tests must stay green throughout.
```

### Success Criteria Separation

Each phase must have distinct success criteria:

**Phase 1 Success Criteria:**
```markdown
#### Automated Verification:
- [ ] Tests execute: `pytest tests/test_feature.py -v`
- [ ] Tests fail as expected (feature not implemented)
- [ ] No syntax errors: `make mypy`

#### Manual Verification:
- [ ] Test coverage includes all edge cases
- [ ] Test assertions are specific and meaningful
```

**Phase 2 Success Criteria:**
```markdown
#### Automated Verification:
- [ ] All tests pass: `make test`
- [ ] Type checking passes: `make mypy`
- [ ] Linting passes: `make lint`

#### Manual Verification:
- [ ] Feature works in paper trading
- [ ] Logs show expected behavior
```

## When TDD Doesn't Apply

TDD is **mandatory** for new features, but these scenarios have different workflows:

### Bug Fixes
- Can modify tests and implementation together
- Write regression test that reproduces bug
- Fix implementation to pass new test
- No strict phase separation required

### Refactoring Existing Code
- Tests already exist
- Refactor implementation
- Tests must stay green
- No test modifications unless improving test quality

### Documentation Updates
- No TDD required
- Update docs directly

### Configuration Changes
- No TDD required for config-only changes
- May require tests if config affects behavior

## TDD Best Practices for This Project

### Critical Testing Rules (Always Follow)

1. **Reuse Before Creating**: Before creating new test fixtures or factories:
   - Check `conftest.py` for existing fixtures (`test_database`, `mock_alpaca_service`, etc.)
   - Check `tests/factories.py` for data factories (`create_polygon_trade`, `create_bar_data`, etc.)
   - Consider if existing fixtures can be parametrized or extended
   - Only create new fixtures/factories when truly needed

2. **Check Test Coverage First**:
   - Run `make test` to see current coverage reports
   - Avoid writing tests that duplicate existing coverage
   - Focus on untested scenarios and edge cases
   - Look for gaps in the coverage report

3. **Parametrize for Maintainability**:
   - Use `@pytest.mark.parametrize` to test multiple scenarios with one test function
   - Reduces code duplication in test files
   - Makes it easier to add new test cases
   - Example below

4. **NO Imports Inside Functions**:
   - **NEVER** import modules inside function bodies
   - Only exception: Avoiding circular imports (must document)
   - Circular import example requires TODO comment for humans to fix
   - Top-level imports are always preferred

5. **Database Testing Strategy**:
   - **Use real DB** (`test_database` fixture): Integration tests, DB adapter tests, SQLAlchemy query validation
   - **Mock DB**: Unit tests for business logic where DB is incidental
   - **Rule of thumb**: Testing database behavior/queries/relationships → real DB. Testing algorithm/logic → mock DB.

For a comprehensive reference on this, see [best-practices.md](best-practices.md).

### Use Pytest Features
```python
# Parametrized tests for multiple scenarios
@pytest.mark.parametrize("input,expected", [
    ("valid", True),
    ("", False),
    (None, ValueError),
])
async def test_various_inputs(input, expected):
    if expected == ValueError:
        with pytest.raises(ValueError):
            service = NewService(input)
    else:
        service = NewService(input)
        result = await service.process()
        assert result.success == expected
```

### Mock External Dependencies
```python
# Mock Alpaca API calls
@pytest.mark.asyncio
async def test_with_mocked_broker(mock_alpaca_service):
    mock_alpaca_service.buy.return_value = OrderResponse(id="order123")

    bot = SingleAssetBot(broker=mock_alpaca_service)
    await bot.enter(price=100.0)

    mock_alpaca_service.buy.assert_called_once_with(
        symbol="TSLA",
        qty=50,
        price=100.0
    )
```

### Test Async Code Properly
```python
# Always use @pytest.mark.asyncio
@pytest.mark.asyncio
async def test_async_operation():
    result = await async_function()
    assert result is not None

# Use AsyncMock for async methods
from unittest.mock import AsyncMock

mock_service.async_method = AsyncMock(return_value="result")
```

### Follow Fixture Patterns
```python
# Create reusable fixtures in conftest.py
@pytest.fixture
async def test_database():
    """Temporary database for testing"""
    db_path = "test_temp.db"
    db = SQLAlchemyAdapter(db_path)

    yield db

    # Cleanup
    os.remove(db_path)
```

### Avoid Imports Inside Functions
```python
# ❌ WRONG - Import inside function
def test_feature():
    from trading.services import SomeService  # DON'T DO THIS!
    service = SomeService()

# ✅ RIGHT - Top-level import
from trading.services import SomeService

def test_feature():
    service = SomeService()

# ⚠️ ONLY IF CIRCULAR IMPORT (and document it!)
def test_feature():
    # TODO: Fix circular import between trading.services and trading.bots
    from trading.services import SomeService
    service = SomeService()
```

### Check Coverage Before Writing Tests
```bash
# Run tests with coverage to see what's already tested
make test

# Look for untested lines/branches in the report
# Focus new tests on gaps in coverage
# Don't duplicate tests for already-covered code
```

### Reuse Existing Fixtures and Factories
```python
# ❌ WRONG - Creating new fixture when one exists
@pytest.fixture
def my_test_database():  # Don't create duplicate!
    return SQLAlchemyAdapter("another_test.db")

# ✅ RIGHT - Use existing fixture from conftest.py
async def test_with_database(test_database):
    # Use the existing test_database fixture
    position = await test_database.create_position(...)

# ✅ RIGHT - Extend existing factory
from tests.factories import create_polygon_trade

def test_custom_trade():
    # Use factory with custom parameters
    trade = create_polygon_trade(
        price=100.0,
        size=500,
        conditions=[12]  # Regular sale
    )
```

## Common TDD Antipatterns to Avoid

### ❌ Writing Implementation First
```python
# WRONG: Implementation before tests
# 1. Write new_service.py
# 2. Then write test_new_service.py
```

### ❌ Modifying Tests to Pass
```python
# WRONG: Changing test to match broken implementation
def test_calculation():
    result = calculator.add(2, 2)
    assert result == 5  # Changed from 4 to match bug!
```

### ❌ Skipping Test Cases
```python
# WRONG: Only testing happy path
async def test_only_success():
    result = await service.process("valid")
    assert result.success is True

# Missing: error cases, edge cases, boundary conditions
```

### ❌ Testing Implementation Details
```python
# WRONG: Testing internal private methods
def test_internal_method():
    service = NewService()
    result = service._internal_helper()  # Don't test private methods!
    assert result == "something"

# RIGHT: Test public interface
async def test_public_behavior():
    service = NewService(param="value")
    result = await service.process()
    assert result.success is True
```

## Summary

**TDD in this project means**:
1. ✅ Tests define behavior (Phase 1)
2. ✅ Code satisfies tests (Phase 2)
3. ✅ Refactor while keeping tests green (Phase 3)
4. ✅ Strict separation between phases
5. ✅ No implementation without tests
6. ✅ No test modifications during implementation

**This ensures**:
- Clear feature specifications
- Comprehensive test coverage
- Confident refactoring
- Regression prevention
- Better code design
