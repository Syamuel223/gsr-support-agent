# GSR Shipping & Delivery Policy

## Standard Delivery Timelines
- **Metro cities** (Bengaluru, Mumbai, Delhi, Chennai, Hyderabad, Pune,
  Kolkata): 2-4 business days.
- **Tier-2 cities** (Ahmedabad, Jaipur, Lucknow, and similar): 4-7 business
  days.
- **Remote/rural pin codes**: 7-10 business days.

These are estimates shown at checkout as `estimated_delivery_date`; actual
delivery can occasionally run later due to courier delays, weather, or
regional restrictions.

## Order Status Definitions
- `processing`: order confirmed, being packed at the warehouse.
- `shipped`: handed off to the courier partner, in transit to the
  destination hub.
- `out_for_delivery`: with the local delivery agent, expected same day.
- `delivered`: successfully delivered to the customer.
- `cancelled`: order cancelled (by customer before shipping, or by GSR due
  to stock/payment issues).
- `returned`: delivered, then successfully returned by the customer.

## What Counts as a "Delayed" Order
An order is considered delayed if the current date is past the
`estimated_delivery_date` and the status is not yet `delivered`. For orders
already marked `delivered`, a delivery is considered "late" if
`delivered_date` is after `estimated_delivery_date` -- this is tracked for
internal SLA reporting and is also used to prioritize how apologetic and
proactive the support response should be.

## Shipping Charges
- Orders above ₹499: free standard shipping.
- Orders below ₹499: a flat ₹49 shipping fee applies.
- **Prime tier customers**: free shipping on all orders regardless of
  order value, plus priority courier handling that typically shaves
  0.5-1 day off standard timelines.

## Cancellations
- Orders can be cancelled by the customer any time before the status
  changes to `shipped`.
- Once `shipped`, the order cannot be cancelled -- the customer must wait
  for delivery and then initiate a return instead.
- Cancelled orders are refunded in full within 2-4 business days to the
  original payment method (instant for UPI/wallet).

## Failed Delivery Attempts
If a delivery attempt fails (customer unavailable, wrong address, etc.),
the courier will attempt delivery up to 2 more times over the following
2-3 days. After 3 failed attempts, the order is automatically marked for
return-to-origin and the customer is refunded once it's back at the
warehouse.

## International Shipping
GSR currently ships only within India. There is no international shipping
option at this time.
