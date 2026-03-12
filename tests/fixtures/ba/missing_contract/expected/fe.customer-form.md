# FE Spec: Customer Form

- Screen id: `customer-form`
- Purpose: Capture customer details while backend contract details remain provisional.
- Roles: Sales
- Entry points: Customer List
- Exit points: Customer List
- Dependencies: Create Customer
- Resolved mode: `FE_FIRST`
- FE ready: `true`
- BE ready: `false`

## User Intent

Capture customer details while backend contract details remain provisional.

## States

- Persist the captured form values while the provisional create request is in flight.

## Fields and Validations

### `email`

- Label: Email
- Type: `email`
- Required: `true`
- Source domain: `FE`
- Fact status: `CONFIRMED`
- Description: _none_
- Traceability: `field-email` / evidence=1

### `legal_name`

- Label: Legal Name
- Type: `text`
- Required: `true`
- Source domain: `FE`
- Fact status: `CONFIRMED`
- Description: _none_
- Traceability: `field-legal-name` / evidence=1

### `loyalty_tier`

- Label: Loyalty Tier
- Type: `select`
- Required: `true`
- Source domain: `FE`
- Fact status: `CONFIRMED`
- Description: _none_
- Traceability: `field-loyalty-tier` / evidence=1

### `sales_owner_id`

- Label: Sales Owner
- Type: `text`
- Required: `true`
- Source domain: `FE`
- Fact status: `CONFIRMED`
- Description: _none_
- Traceability: `field-sales-owner` / evidence=1


## Actions

- Save customer

## Visible Business Rules

- [CONFIRMED] Show a manager-approval banner before submission. Trigger: Requested loyalty tier is VIP. Outcome: FE preserves captured values while approval state stays provisional..

## API Dependencies or Provisional Contracts

- [PROVISIONAL] provisional `POST` `/customers` for Create Customer

## Loading/Error/Empty States

- [PROVISIONAL] Persist the captured form values while the provisional create request is in flight.

## Open FE Questions

_No open FE questions remain._

## Provisional Markers

- `loading_state` remains provisional: Persist the captured form values while the provisional create request is in flight.
- `endpoint` remains provisional: /customers
- required assumption: Assume the provisional response echoes saved customer values and approval state.