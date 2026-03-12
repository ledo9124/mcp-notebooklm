# Questions Backlog

- Feature key: `customer-create`
- Run id: `run-missing-contract-golden`
- Screen id: `customer-form`
- Schema version: `ba.gap_review.v1.0`
- FE blockers: 0
- BE blockers: 1
- Shared blockers: 0
- Required assumptions: 1
- Contradictions: 0
- Open questions: 1

## MISSING

### FE blockers

_None._

### BE blockers

- [HIGH] `MISSING_BACKEND_CONTRACT` Authoritative Create Customer response schema is still missing. (owner: Tech Lead; workstreams: BE)

### Shared blockers

_None._

### Required assumptions

- [MEDIUM] `REQUIRED_ASSUMPTION` Assume the provisional response echoes saved customer values and approval state. (owner: Tech Lead; workstreams: FE)

### Non-blockers

_None._

## CONTRADICTED

_No contradictions recorded._

## QUESTION_FOR_BA

_None._

## QUESTION_FOR_TECH_LEAD

- [HIGH] What response envelope should Create Customer return while approval is pending? (owner: Tech Lead; workstreams: BE)

## QUESTION_FOR_DESIGN

_None._