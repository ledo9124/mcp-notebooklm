# BE Spec: Customer Form

- Screen id: `customer-form`
- Purpose: Capture customer details while backend contract details remain provisional.
- Roles: Sales
- Main actions: Save customer
- Dependencies: Create Customer
- Resolved mode: `FE_FIRST`
- FE ready: `true`
- BE ready: `false`

## Implementation Intent

Capture customer details while backend contract details remain provisional.

## Entities and Data Contracts

- [CONFIRMED] `email` (email; required=true; source=`FE`; trace=`field-email` / evidence=1)
- [CONFIRMED] `legal_name` (text; required=true; source=`FE`; trace=`field-legal-name` / evidence=1)
- [CONFIRMED] `loyalty_tier` (select; required=true; source=`FE`; trace=`field-loyalty-tier` / evidence=1)
- [CONFIRMED] `sales_owner_id` (text; required=true; source=`FE`; trace=`field-sales-owner` / evidence=1)

## Workflows and Business Rules

- [CONFIRMED] `Save customer`: Show a manager-approval banner before submission. Trigger: Requested loyalty tier is VIP. Outcome: FE preserves captured values while approval state stays provisional.. (source=`SHARED`; trace=`approval-banner-rule` / evidence=1)

## Endpoints, Events, and Jobs

- [PROVISIONAL] `ENDPOINT` Create Customer: `POST`  `/customers` (request: legalName, email, loyaltyTier, salesOwnerId; response: customerId, approvalState; trace=`endpoint-create-customer` / evidence=1)

## Validation Rules and Permissions

- [CONFIRMED] Show a manager-approval banner before submission. (action=`Save customer`; trace=`approval-banner-rule` / evidence=1)

## Contradictions

_No contradictions recorded._

## Open BE Questions

- [HIGH] What response envelope should Create Customer return while approval is pending? (owner: Tech Lead; workstreams: BE; evidence=1)
- [HIGH] blocker: Authoritative Create Customer response schema is still missing. (owner: Tech Lead; workstreams: BE; evidence=1)