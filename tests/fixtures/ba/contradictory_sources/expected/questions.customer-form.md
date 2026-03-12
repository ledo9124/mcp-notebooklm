# Questions Backlog

- Feature key: `customer-create`
- Run id: `run-contradictory-golden`
- Screen id: `customer-form`
- Schema version: `ba.gap_review.v1.0`
- FE blockers: 0
- BE blockers: 0
- Shared blockers: 2
- Required assumptions: 0
- Contradictions: 2
- Open questions: 2

## MISSING

### FE blockers

_None._

### BE blockers

_None._

### Shared blockers

- [HIGH] `CONTRADICTORY_REQUIREMENT_DETAIL` Email validation timing is inconsistent across the BA sources. (owner: BA; workstreams: SHARED)
- [HIGH] `CONTRADICTORY_REQUIREMENT_DETAIL` VIP approval threshold differs between the BA PDF and the rules addendum. (owner: BA; workstreams: SHARED)

### Required assumptions

_None._

### Non-blockers

_None._

## CONTRADICTED

### `email-validation-timing`

- Severity: `HIGH`
- Summary: Requirements disagree on when duplicate-email validation runs.
- Resolution question: Should duplicate-email validation run on blur or only on submit?
- Claims:
  - Validate email only when the user presses Save.
  - Validate email on blur before Save.

### `vip-approval-threshold`

- Severity: `HIGH`
- Summary: The spend threshold for VIP approval is inconsistent across the sources.
- Resolution question: Which yearly-spend threshold is authoritative for VIP approval?
- Claims:
  - Manager approval is required only above a 10000 yearly-spend threshold.
  - Manager approval is required above a 5000 yearly-spend threshold.

## QUESTION_FOR_BA

- [HIGH] Should duplicate-email validation run on blur or only on submit? (owner: BA; workstreams: SHARED)
- [HIGH] Which yearly-spend threshold is authoritative for VIP approval? (owner: BA; workstreams: SHARED)

## QUESTION_FOR_TECH_LEAD

_None._

## QUESTION_FOR_DESIGN

_None._
