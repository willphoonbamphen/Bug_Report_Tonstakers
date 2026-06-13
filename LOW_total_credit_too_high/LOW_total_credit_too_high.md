# LOW: pool.func `total_credit_too_high` check allows borrowing `max_loan_per_validator + interest`

**Severity:** Low  
**Component:** `contracts/pool.func` line 348  
**Error code:** `error::total_credit_too_high` (0xf103)

---

## Summary

The `pool::request_loan` handler checks per-controller accumulated borrowing against a cap of `max_loan_per_validator + interest` rather than `max_loan_per_validator`. The spurious `+ interest` term allows up to one round's worth of interest (~100–1 526 TON at typical interest rates) beyond the intended cap.

---

## Vulnerable Code

```func
;; pool.func line 347-348
int total_loan = current_round_borrowers~add_loan(sender_address, actual_loan, interest);
throw_unless(error::total_credit_too_high, total_loan <= max_loan_per_validator + interest);
//                                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
//                                         Should be: total_loan <= max_loan_per_validator
```

`add_loan` returns `already_borrowed` — the accumulated **principal** (not including interest) for this controller in the current round. The correct cap is therefore `max_loan_per_validator`, not `max_loan_per_validator + interest`.

---

## Impact

If a controller were to hold two simultaneous loans in the pool's borrowers dict totalling `principal₁ + principal₂ > max_loan_per_validator`, the check only fires at `principal₁ + principal₂ > max_loan_per_validator + interest`. The excess window is:

```
excess = muldiv(actual_loan, interest_rate, SHARE_BASIS)
       ≈ 100 TON  (prod rate ~0.01 %/round)
       ≈ 1 526 TON  (test rate ~0.15 %/round)
```

**Currently exploitable?** No — the controller contract blocks multiple concurrent loans via:
```func
throw_if(error::multiple_loans_are_prohibited, borrowed_amount);
```
If that guard is relaxed or a future credit path bypasses it, this pool-side check becomes the sole defence and it is insufficient.

---

## Proof of Concept

```
$ python3 poc_total_credit_too_high.py

Scenario 2 — accumulated principal across two loans
  loan_1 = max_loan_per_validator  : 1,000,000.0000 TON
  loan_2 = interest(loan_1)        :     1,525.8789 TON
  total_loan (accumulated)         : 1,001,525.8789 TON

  Defective check: 1001525878906250 ≤ 1001525878906250  → PASS ✓ (bug allows it)
  Correct  check:  1001525878906250 ≤ 1000000000000000  → FAIL ✗ (should reject)

  Extra TON that bypasses the cap: 1,525.8789 TON
```

---

## Recommendation

```func
// pool.func line 348 — fix:
throw_unless(error::total_credit_too_high, total_loan <= max_loan_per_validator);
```

Remove `+ interest` from the right-hand side. The interest component is accounted for in `expected` (not `borrowed`) and does not need to be part of the principal cap.
