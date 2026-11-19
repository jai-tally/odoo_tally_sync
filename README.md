# Odoo ↔ TallyPrime Real-Time Sync

A custom Odoo 20 Community module that **automatically pushes** confirmed accounting entries from Odoo to **TallyPrime** via its built-in HTTP/XML gateway (port 9000) — in real time.

---

## ✅ Supported Document Types

| Odoo Document | Tally Voucher |
|---|---|
| Customer Invoice | Sales Voucher |
| Vendor Bill | Purchase Voucher |
| Customer Credit Note | Credit Note Voucher |
| Vendor Debit Note | Debit Note Voucher |
| Expense Receipt | Journal Voucher |
| Customer Receipt (Payment) | Receipt Voucher |
| Vendor Payment | Payment Voucher |

---

## ✨ Features

- **Real-time push** on document confirmation (`_post()` / `action_post()`)
- **Discount Allowed / Discount Received** sync — gross sales/purchase ledger with separate discount line (balanced voucher)
- **Cash Rounding / Round Off** sync
- **Auto-creates Tally Ledgers** (partners, VAT, discount, round-off, bank/cash) before each push
- **Retry queue** — cron retries failed pushes up to N times
- **Manual re-sync button** on every invoice and payment form
- **Sync Log** — full audit trail with XML sent, Tally response, error messages
- **Bulk Retry Failed** wizard
- **UAE VAT** support (5% standard, zero-rated, exempt)
- **Odoo 20 compatible** (`models.Constraint`, `invisible=`, `ir.access.csv` format)

---

## 🛠️ Installation

### Requirements
- Odoo 20.0 Community (Windows or Linux)
- TallyPrime with HTTP XML Gateway enabled on port `9000`

### Steps

1. **Copy the module** to your Odoo addons path:
   ```
   H:\odoo anti\odoo_tally_sync\   (Windows example)
   ```

2. **Add to `addons_path`** in `odoo.conf`:
   ```ini
   addons_path = C:\Program Files\Odoo 20.0\server\odoo\addons,H:\odoo anti
   ```

3. **Restart Odoo** and update the module list.

4. **Install** the module: `Apps → Search "TallyPrime Sync" → Install`

---

## ⚙️ Configuration

Go to **TallyPrime Sync → Configuration** and fill in:

| Field | Example |
|---|---|
| TallyPrime Company Name | `Odoo` (exact name in Tally) |
| Tally Host | `localhost` |
| Tally Port | `9000` |
| Sales Ledger | `Sales` |
| Purchase Ledger | `Purchase` |
| Output VAT Ledger | `Output VAT 5%` |
| Input VAT Ledger | `Input VAT 5%` |
| Expense Ledger | `Indirect Expenses` |
| Discount Allowed Ledger | `Discount Allowed` |
| Discount Received Ledger | `Discount Received` |
| Round Off Ledger | `Round Off` |
| Cash Ledger | `Cash` |
| Bank Ledger | `Bank` |

> **Enable Tally XML Gateway:** In TallyPrime → `F1 Help → Settings → Connectivity → Enable ODBC Server`

---

## 📐 Tally XML Voucher Structure

### Sales (with Discount)
```
Party Ledger        DEBIT   (-236.25)   ← amount_total
Sales Ledger        CREDIT  (+250.00)   ← gross (net + discount)
Discount Allowed    DEBIT   (-25.00)    ← discount amount
Output VAT 5%       CREDIT  (+11.25)    ← tax
```

### Receipt (Customer Payment)
```
Bank/Cash           DEBIT   (-amount)
Customer Party      CREDIT  (+amount)
```

### Payment (Vendor Payment)
```
Vendor Party        DEBIT   (-amount)
Bank/Cash           CREDIT  (+amount)
```

---

## 📂 Module Structure

```
odoo_tally_sync/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── tally_config.py          # Configuration model
│   ├── tally_client.py          # HTTP client for Tally gateway
│   ├── tally_xml_builder.py     # XML builders for all voucher types
│   ├── tally_sync_log.py        # Sync log + cron retry
│   ├── account_move.py          # Invoice/Bill/CN/DN/Expense push
│   └── account_payment.py       # Receipt/Payment push
├── views/
│   ├── tally_config_views.xml
│   ├── tally_sync_log_views.xml
│   ├── account_move_views.xml
│   ├── account_payment_views.xml
│   └── menu_views.xml
├── wizard/
│   └── tally_retry_wizard_views.xml
├── security/
│   └── ir.access.csv
└── data/
    └── tally_sync_cron.xml
```

---

## 🔄 Sync Flow

```
Odoo Invoice Confirmed
        ↓
_push_to_tally()
        ↓
_ensure_partner_ledger()   → Auto-create Tally ledger master
_ensure_discount_ledgers() → Auto-create discount/roundoff ledgers
        ↓
build_sales_xml() / build_payment_xml() / ...
        ↓
TallyClient.send(xml)      → HTTP POST to localhost:9000
        ↓
Parse <CREATED> / <EXCEPTIONS>
        ↓
tally_sync_status = 'synced' or 'failed'
        ↓
tally.sync.log record created
```

---

## 📋 License

LGPL-3.0

---

## 👤 Author

Custom module built for Odoo 20 Community + TallyPrime integration (UAE).
