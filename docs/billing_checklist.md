# Billing Module — Manual Test Checklist

Covers Sprint 31 (Billing Run Engine) and Sprint 32 (Invoice Rendering, Delivery & Audit).
Work through the steps in order — each builds on the previous one.

---

## Prerequisites

Before starting, confirm the following exist in the system:

- [ ] A **Site** with at least one active **Device**
- [ ] That device has a **Stream** with `billing_role = generation` and existing `IntervalAggregate` data
  - If no aggregate data exists, run: `docker compose exec backend python manage.py seed_perf_data`
- [ ] A PPA tariff **Reference Dataset** (`scope=tenant`) with at least one flat-rate row
  - Create via: **That Place Admin → Reference Datasets → New**
- [ ] A **Billing Account** (`ppa_host`) with `invoice_email_recipients` set to an inbox you can check

---

## How to Assign a Reference Dataset to a Tenant

Reference datasets are assigned per-site (or tenant-wide) via **Dataset Assignments**.
The assignment tells the billing engine which tariff rows apply to a given site.

**Step-by-step:**

1. Log in as Tenant Admin → go to **Datasets** in the nav
2. Click **New assignment**
3. **Dataset** — select the tariff dataset (e.g. `network-tariffs` or your PPA tariff)
4. **Site** — select a specific site, or leave blank for tenant-wide
5. **Dimension filter (JSON)** — enter the key/value pairs that identify the correct rows.
   The dimension keys are shown next to the field label.
   Example for `network-tariffs`:
   ```json
   { "distributor_slug": "ausgrid", "tariff_code": "EA305" }
   ```
6. **Version pin** — leave blank to always use the latest active version, or pin to e.g. `2025-26`
7. **Effective from** — date the assignment starts applying
8. Click **Save**, then **Preview** to confirm the correct row(s) resolve

The billing engine reads this assignment at run time to look up the rate for each
interval. The dimension filter narrows the dataset rows down to the ones that apply
to this specific site/customer.

---

## 1. Billing Accounts & Tariffs (Sprint 30 baseline)

- [ ] Go to `/app/billing-accounts` → create a `ppa_host` account, set `invoice_email_recipients`
- [ ] Open the account detail → **Meters** tab → link the generation stream, set `effective_from`
- [ ] **Tariffs** tab → assign the PPA tariff dataset with a dimension filter and version

---

## 2. Billing Runs (Sprint 31)

- [ ] Go to `/app/billing-runs` → **New run**
  - Select the site
  - Set a period that covers your interval aggregate data
  - Aggregate period: `30min`
  - Submit
- [ ] Watch the status badge cycle: `queued → computing → draft` (refresh the page)
- [ ] Open the run detail → **Line Items** tab
  - Verify energy lines appear with correct kWh and dollar amounts
  - Verify supply line appears
  - Check GST amounts are 10% of the pre-GST amount per line
- [ ] **Snapshot** tab — verify computed kWh matches expectations
- [ ] Hit **Recompute** → run rebuilds from `queued → computing → draft`; line items should be identical
- [ ] **Force a failure and retry:**
  - Temporarily delete the tariff assignment
  - Hit **Recompute** → run goes to `failed`, failure detail explains the missing tariff
  - Restore the tariff assignment
  - Hit **Retry** → run recovers to `draft`

---

## 3. Finalize & Invoices (Sprint 32)

> **PDF note:** PDF rendering requires WeasyPrint. Run `docker compose up -d --build` before
> testing the PDF preview. Without rebuilding, invoices are created and emailed but the
> PDF attachment and in-app preview will be missing.

- [ ] On a `draft` run → hit **Finalize** → status moves to `finalized`
- [ ] **Invoices** tab → one invoice row appears per billing account
  - Status: `draft` or `delivered`
  - Delivery status: `pending` → `sent` (may take a few seconds for Celery)
- [ ] Check your email inbox — invoice email arrives:
  - Subject: `Tax Invoice INV-YYYY-NNNN — Jan 2026`
  - Body includes invoice total and 14-day download link
  - PDF attached (requires container rebuild)
- [ ] Click **View →** on the invoice → `/app/invoices/:id`
  - PDF preview loads in the iframe *(requires rebuild)*
  - Metadata panel shows correct subtotal / GST / total
  - Delivery status shows `sent`
- [ ] Hit **Resend** → delivery status resets to `pending`, second email arrives
- [ ] Try to **Recompute** a finalized run → 400 error toast ("Only draft or review runs can be recomputed")

---

## 4. Void Workflow (Sprint 32)

- [ ] On a `finalized` run → hit **Void** → modal appears
  - Enter a reason, leave "silent void" unchecked
  - Confirm → run goes to `voided`, all invoices go to `void`
- [ ] Check inbox — void-notification email arrives:
  - Subject: `VOID NOTICE — Invoice INV-...`
  - Reason string appears in the body
- [ ] Invoice detail → void status indicator displayed; **Resend** returns 400
- [ ] **Silent void test:**
  - Create and finalize a second billing run
  - Void with "suppress void-notification emails" checked
  - No email should arrive for the voided invoices

---

## 5. CSV Export (Sprint 32)

- [ ] On any run with line items → **Line Items** tab → **Download CSV**
- [ ] Open the CSV — verify columns present:
  `account_name, customer_reference, line_kind, period_name, kwh, rate_cents_per_kwh, amount_cents, gst_cents, total_cents, quality_summary`
- [ ] Verify energy + supply rows both present with correct values
- [ ] Verify a large export (e.g. 30-day period, multiple accounts) downloads without timeout

---

## 6. Billing Schedules (Sprint 32)

- [ ] Go to `/app/billing-schedules` → **New schedule**
  - Cadence: **Monthly (anchor day)** → verify `Anchor day` field appears
  - Try saving without anchor day → validation error
- [ ] Set cadence to **Monthly (calendar)**, enable **Auto-finalize** → save
- [ ] Confirm schedule appears in list with a future `Next run` date
- [ ] Edit → toggle to inactive → badge changes
- [ ] Delete → schedule disappears

---

## Key things to watch for

| Check | What failure looks like | Fix |
|---|---|---|
| PDF preview blank | WeasyPrint not installed | `docker compose up -d --build` |
| Email not received | Dev uses console backend | Check `EMAIL_BACKEND` in `.env` |
| Signed URL 403 | S3/MinIO creds not configured | Check `AWS_*` env vars |
| Run stays in `computing` | Celery worker not running | `docker compose up celery_worker` |
| Invoice number gaps | Concurrent finalize edge case | Check `Tenant.invoice_number_sequence` in Django shell |
| No datasets in dropdown | Datasets not seeded or inactive | Check That Place Admin → Reference Datasets |
