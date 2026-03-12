# BE Spec: Customer Form

- Screen id: `customer-form`
- Purpose: Create a customer record and capture approval-state inputs.
- Roles: Sales
- Main actions: Save customer
- Dependencies: Create Customer
- Resolved mode: `BALANCED`
- FE ready: `true`
- BE ready: `true`

## Implementation Intent

Create a customer record and capture approval-state inputs.

## Entities and Data Contracts

- [CONFIRMED] `email` (email; required=true; source=`FE`; trace=`field-email` / evidence=1)
- [CONFIRMED] `legal_name` (text; required=true; source=`FE`; trace=`field-legal-name` / evidence=1)
- [CONFIRMED] `loyalty_tier` (select; required=true; source=`FE`; trace=`field-loyalty-tier` / evidence=1)
- [CONFIRMED] `sales_owner_id` (text; required=true; source=`FE`; trace=`field-sales-owner` / evidence=1)

## Workflows and Business Rules

- [CONFIRMED] `Save customer`: Duplicate email addresses block creation immediately. Trigger: User clicks Save. Outcome: Show inline duplicate-email validation and keep Save disabled.. (source=`SHARED`; trace=`form-save-rule` / evidence=1)
- [CONFIRMED] `Save customer`: VIP customers require an approval flag before save completes. Trigger: Requested loyalty tier is VIP. Outcome: Return approvalFlag=pending until manager review completes.. (source=`SHARED`; trace=`vip-approval-flag` / evidence=1)

## Endpoints, Events, and Jobs

- [CONFIRMED] `ENDPOINT` Create Customer: `POST`  `/customers` (request: legalName, email, loyaltyTier, salesOwnerId; response: customerId, status, approvalFlag; trace=`endpoint-create-customer` / evidence=1)

## Validation Rules and Permissions

- [CONFIRMED] Duplicate email addresses block creation immediately. (action=`Save customer`; trace=`form-save-rule` / evidence=1)
- [CONFIRMED] VIP customers require an approval flag before save completes. (action=`Save customer`; trace=`vip-approval-flag` / evidence=1)

## Contradictions

_No contradictions recorded._

## Open BE Questions

_No open BE questions remain._