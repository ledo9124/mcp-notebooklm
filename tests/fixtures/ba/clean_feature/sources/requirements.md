# Customer Create Requirements

## Customer List
- Show customer name, loyalty tier, and status chip.
- Selecting a row opens Customer Form in edit mode.

## Customer Form
- Required fields: legal name, email, loyalty tier, sales owner.
- Save remains disabled until legal name and email are valid.
- VIP customers require an approval flag before save completes.

## Acceptance Criteria
- Successful create returns to Customer List with a fresh status chip.
- Duplicate email errors show inline next to the email field.
