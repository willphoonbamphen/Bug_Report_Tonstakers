#!/usr/bin/env python3
"""
PoC: pool.func total_credit_too_high check allows extra borrowing equal to one round's interest

Bug:    pool.func line 348
        throw_unless(error::total_credit_too_high,
                     total_loan <= max_loan_per_validator + interest);
                                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        Should be:  total_loan <= max_loan_per_validator
        Actual:     total_loan <= max_loan_per_validator + interest

Root cause:
  add_loan() returns `already_borrowed` (principal only, not including interest).
  The check should cap the principal to max_loan_per_validator.
  The spurious `+ interest` widens the cap by one round's worth of interest.

Impact path (requires two conditions to align):
  1. A controller obtains an initial loan equal to max_loan_per_validator
     (possible because pool.func computes: actual_loan = min(available_funds, max_loan))
  2. Without that loan being closed in the pool's borrowers_dict, a second
     request_loan call for the same controller arrives and add_loan accumulates
     principal beyond max_loan_per_validator.
     The defective check allows up to max_loan_per_validator + interest to pass,
     so an extra `interest` nanoTON can slip through unchecked.

Note: the controller-side `throw_if(error::multiple_loans_are_prohibited, borrowed_amount)`
currently prevents scenario 2 in normal operation.  If that guard is ever relaxed
(or bypassed via an alternative credit path), this check is the only pool-side defence
and it is insufficient.
"""

# ── on-chain constants (contracts/types.func, contracts/pool.func) ────────────
SHARE_BASIS          = 256 * 256 * 256  # 16_777_216  (24-bit divisor)
ONE_TON              = 1_000_000_000    # nanoTON
DISBALANCE_TOLERANCE = 30               # 30/256 ≈ 11.7 % headroom
MAX_LOAN_DICT_DEPTH  = 12

# default pool configuration (wrappers/Pool.ts)
MAX_LOAN_PER_VALIDATOR = 1_000_000 * ONE_TON   # 1 000 000 TON
MIN_LOAN_PER_VALIDATOR =       100 * ONE_TON   #       100 TON

# test interest rate from PoolConstants.ts: 100 << 8 = 25 600
# production typically ~1 677 (≈ 0.01 %/round)
TEST_INTEREST_RATE   = 100 << 8   # 25 600 / 16 777 216 ≈ 0.1526 %
PROD_INTEREST_RATE   = 1_677      # realistic mainnet value

# ── FunC muldiv (integer, floor division) ─────────────────────────────────────
def muldiv(a: int, b: int, c: int) -> int:
    return (a * b) // c

# ── helper: format nanoTON as human-readable ──────────────────────────────────
def fmt(nano: int) -> str:
    return f"{nano / ONE_TON:,.4f} TON  ({nano:_} nanoTON)"

# ── reproduce the pool.func request_loan logic ────────────────────────────────
def simulate(label: str, actual_loan: int, interest_rate: int, max_lpv: int) -> None:
    interest   = muldiv(actual_loan, interest_rate, SHARE_BASIS)
    total_loan = actual_loan           # add_loan returns `already_borrowed` (principal only)

    defective_limit = max_lpv + interest
    correct_limit   = max_lpv

    passes_defective = total_loan <= defective_limit
    passes_correct   = total_loan <= correct_limit

    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    print(f"  actual_loan          : {fmt(actual_loan)}")
    print(f"  interest_rate        : {interest_rate}/{SHARE_BASIS}  "
          f"≈ {interest_rate/SHARE_BASIS*100:.4f}%")
    print(f"  interest (one round) : {fmt(interest)}")
    print(f"  total_loan           : {fmt(total_loan)}")
    print(f"  max_loan_per_validator: {fmt(max_lpv)}")
    print()
    print(f"  Defective check (actual):   total_loan ≤ max_lpv + interest  "
          f"= {fmt(defective_limit)}")
    print(f"  Correct  check (intended): total_loan ≤ max_lpv              "
          f"= {fmt(correct_limit)}")
    print()
    print(f"  ✓ passes defective check : {passes_defective}")
    print(f"  ✓ passes correct  check  : {passes_correct}")
    print(f"  Δ (excess allowed)       : {fmt(defective_limit - correct_limit)}")

# ── scenario 1: single loan at maximum ────────────────────────────────────────
# The pool caps actual_loan = min(available_funds, max_loan_per_validator).
# Both checks pass identically — the bug is harmless in the single-loan case.
simulate(
    "Scenario 1 — single loan at max_loan_per_validator (normal flow)",
    actual_loan   = MAX_LOAN_PER_VALIDATOR,
    interest_rate = TEST_INTEREST_RATE,
    max_lpv       = MAX_LOAN_PER_VALIDATOR,
)

# ── scenario 2: accumulated loan just above max_lpv (requires multi-loan) ────
# If the controller-side guard `multiple_loans_prohibited` is bypassed,
# add_loan accumulates already_borrowed across calls.
# The defective check silently accepts up to max_lpv + interest.
excess = muldiv(MAX_LOAN_PER_VALIDATOR, TEST_INTEREST_RATE, SHARE_BASIS)
accumulated = MAX_LOAN_PER_VALIDATOR + excess  # principal sum of two loans

print(f"\n{'═'*60}")
print("  Scenario 2 — accumulated principal across two loans")
print(f"  (requires bypassing controller-side multiple_loans_prohibited)")
print(f"{'═'*60}")
print(f"  loan_1 = max_loan_per_validator  : {fmt(MAX_LOAN_PER_VALIDATOR)}")
print(f"  loan_2 = interest(loan_1)        : {fmt(excess)}")
print(f"  total_loan (accumulated)         : {fmt(accumulated)}")
print(f"  max_loan_per_validator           : {fmt(MAX_LOAN_PER_VALIDATOR)}")
print()
print(f"  Defective check: {accumulated} ≤ {MAX_LOAN_PER_VALIDATOR + excess}  → "
      f"{'PASS ✓ (bug allows it)' if accumulated <= MAX_LOAN_PER_VALIDATOR + excess else 'FAIL'}")
print(f"  Correct  check: {accumulated} ≤ {MAX_LOAN_PER_VALIDATOR}  → "
      f"{'FAIL ✗ (should reject)' if accumulated > MAX_LOAN_PER_VALIDATOR else 'PASS'}")
print()
print(f"  Extra TON that bypasses the cap: {fmt(excess)}")

# ── scenario 3: realistic production interest rate ────────────────────────────
simulate(
    "Scenario 3 — production interest rate (~0.01 %/round)",
    actual_loan   = MAX_LOAN_PER_VALIDATOR,
    interest_rate = PROD_INTEREST_RATE,
    max_lpv       = MAX_LOAN_PER_VALIDATOR,
)

# ── summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print("  SUMMARY")
print(f"{'═'*60}")
print("""
  Affected file : contracts/pool.func line 348
  Error code    : error::total_credit_too_high (0xf103)

  Defective:
    throw_unless(error::total_credit_too_high,
                 total_loan <= max_loan_per_validator + interest);

  Fix:
    throw_unless(error::total_credit_too_high,
                 total_loan <= max_loan_per_validator);

  Severity: LOW
    - Not exploitable in isolation: the controller contract prevents
      multiple concurrent loans via `borrowed_amount` tracking.
    - Becomes exploitable if the controller-side guard is ever relaxed
      or if a future code path allows add_loan to accumulate without
      an intervening close_loan.
    - Maximum excess = one round's worth of interest on max_loan_per_validator
      ≈ 100–1 500 TON depending on the interest_rate setting.
""")
