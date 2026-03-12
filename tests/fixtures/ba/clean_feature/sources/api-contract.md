# Customer Create API Contract

`POST /customers`

## Request
- `legalName`: string
- `email`: string
- `loyaltyTier`: `STANDARD | VIP`
- `salesOwnerId`: string

## Success Response
- `customerId`: string
- `status`: `ACTIVE | PENDING_APPROVAL`
- `approvalFlag`: `not_required | pending`

## Error Response
- `409 DUPLICATE_EMAIL`
- `422 INVALID_LOYALTY_TIER`
