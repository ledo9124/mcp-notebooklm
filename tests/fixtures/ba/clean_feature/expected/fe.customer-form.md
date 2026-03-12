# FE Spec: Customer Form

- Screen id: `customer-form`
- Purpose: Create a customer record and capture approval-state inputs.
- Roles: Sales
- Entry points: Customer List
- Exit points: Customer List
- Dependencies: Create Customer
- Resolved mode: `BALANCED`
- FE ready: `true`
- BE ready: `true`

## User Intent

Create a customer record and capture approval-state inputs.

## States

_No explicit UI states were evidenced._

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

- [CONFIRMED] Duplicate email addresses block creation immediately. Trigger: User clicks Save. Outcome: Show inline duplicate-email validation and keep Save disabled..
- [CONFIRMED] VIP customers require an approval flag before save completes. Trigger: Requested loyalty tier is VIP. Outcome: Return approvalFlag=pending until manager review completes..

## API Dependencies or Provisional Contracts

- [CONFIRMED] `POST` `/customers` for Create Customer

## Loading/Error/Empty States

_No explicit loading, error, or empty states were evidenced._

## Open FE Questions

_No open FE questions remain._

## Provisional Markers

_No provisional FE markers remain._