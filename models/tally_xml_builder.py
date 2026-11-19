# -*- coding: utf-8 -*-
"""
TallyPrime XML Builder
Builds robust, balanced vouchers for TallyPrime using standard Accounting Voucher View.
"""
import logging

_logger = logging.getLogger(__name__)


def _tally_date(date_obj):
    """Convert a Python date/datetime to TallyPrime format YYYYMMDD."""
    if hasattr(date_obj, 'strftime'):
        return date_obj.strftime('%Y%m%d')
    return str(date_obj).replace('-', '')


def _esc(value):
    """Escape XML special characters in string values."""
    if not value:
        return ''
    return (str(value)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


def build_ledger_xml(tally_company, ledger_name, parent_group, opening_balance=0.0):
    """Build XML to create/update a Ledger master in TallyPrime."""
    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>All Masters</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(tally_company)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <LEDGER NAME="{_esc(ledger_name)}" ACTION="Create">
                    <NAME>{_esc(ledger_name)}</NAME>
                    <PARENT>{_esc(parent_group)}</PARENT>
                    <OPENINGBALANCE>{opening_balance}</OPENINGBALANCE>
                </LEDGER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_sales_xml(move, config):
    """
    Build Tally XML for Customer Invoice (Sales Voucher).
    In Tally Accounting View:
      - Party (Debit): ISDEEMEDPOSITIVE=Yes, AMOUNT is negative (-total)
      - Income & Tax (Credit): ISDEEMEDPOSITIVE=No, AMOUNT is positive (+amount)
    """
    partner_name = _esc(move.partner_id.name or 'Cash Customer')
    date_str = _tally_date(move.invoice_date or move.date)
    ref = _esc(move.name or '')
    narration = _esc(move.ref or move.narration or move.name or 'Sales Invoice')
    total_amount = abs(move.amount_total)

    entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>-{total_amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # Income lines — use GROSS amount (net + discount) so the voucher balances
    # when a separate Discount Allowed debit entry is added below.
    income_lines = move.line_ids.filtered(lambda l: l.display_type in ('product', False) and l.account_id.account_type in ('income', 'income_other', 'equity'))
    for line in income_lines:
        net_amt = abs(line.credit - line.debit)
        if net_amt == 0:
            continue
        # Compute the discount amount for this line
        discount_amt = 0.0
        if line.discount and line.discount > 0:
            discount_amt = abs(line.price_unit * line.quantity * line.discount / 100.0)
        # Gross = net (after discount already in journal) + discount
        gross_amt = net_amt + discount_amt
        entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.sales_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{gross_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""
        # Discount Allowed debit — only when discount is present
        if discount_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.discount_allowed_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{discount_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # Tax lines
    tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
    for tax_line in tax_lines:
        tax_amt = abs(tax_line.credit - tax_line.debit)
        if tax_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.vat_output_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{tax_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # Cash rounding (round-off) line
    if move.invoice_cash_rounding_id:
        rounding_lines = move.line_ids.filtered(
            lambda l: l.account_id == move.invoice_cash_rounding_id.account_id
        )
        for r in rounding_lines:
            r_amt = abs(r.balance)
            if r_amt > 0:
                # If balance > 0 it's a credit (income side) → ISDEEMEDPOSITIVE=No, AMOUNT positive
                # If balance < 0 it's a debit (expense side) → ISDEEMEDPOSITIVE=Yes, AMOUNT negative
                is_deemed = 'Yes' if r.balance < 0 else 'No'
                tally_amt = r.balance  # keep sign for Tally
                entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.round_off_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>{is_deemed}</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{tally_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="Sales" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PARTYLEDGERNAME>{partner_name}</PARTYLEDGERNAME>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <ISINVOICE>Yes</ISINVOICE>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_purchase_xml(move, config):
    """
    Build Tally XML for Vendor Bill (Purchase Voucher).
    In Tally Accounting View:
      - Party (Credit): ISDEEMEDPOSITIVE=No, AMOUNT is positive (+total)
      - Expense & Tax (Debit): ISDEEMEDPOSITIVE=Yes, AMOUNT is negative (-amount)
    """
    partner_name = _esc(move.partner_id.name or 'Cash Vendor')
    date_str = _tally_date(move.invoice_date or move.date)
    ref = _esc(move.name or '')
    narration = _esc(move.ref or move.narration or move.name or 'Purchase Bill')
    total_amount = abs(move.amount_total)

    entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>{total_amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    expense_lines = move.line_ids.filtered(lambda l: l.display_type in ('product', False) and l.account_id.account_type in ('expense', 'expense_direct_cost', 'expense_depreciation'))
    for line in expense_lines:
        net_amt = abs(line.debit - line.credit)
        if net_amt == 0:
            continue
        # Compute the discount amount for this line
        discount_amt = 0.0
        if line.discount and line.discount > 0:
            discount_amt = abs(line.price_unit * line.quantity * line.discount / 100.0)
        # Gross = net (after discount already in journal) + discount
        gross_amt = net_amt + discount_amt
        entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.purchase_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{gross_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""
        # Discount Received credit — only when discount is present
        if discount_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.discount_received_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{discount_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
    for tax_line in tax_lines:
        tax_amt = abs(tax_line.debit - tax_line.credit)
        if tax_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.vat_input_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{tax_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # Cash rounding (round-off) line
    if move.invoice_cash_rounding_id:
        rounding_lines = move.line_ids.filtered(
            lambda l: l.account_id == move.invoice_cash_rounding_id.account_id
        )
        for r in rounding_lines:
            r_amt = abs(r.balance)
            if r_amt > 0:
                is_deemed = 'Yes' if r.balance < 0 else 'No'
                tally_amt = -r.balance  # flip sign for purchase perspective
                entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.round_off_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>{is_deemed}</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{tally_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="Purchase" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PARTYLEDGERNAME>{partner_name}</PARTYLEDGERNAME>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <ISINVOICE>Yes</ISINVOICE>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_credit_note_xml(move, config):
    """Build Tally XML for Customer Credit Note."""
    partner_name = _esc(move.partner_id.name or 'Cash Customer')
    date_str = _tally_date(move.invoice_date or move.date)
    ref = _esc(move.name or '')
    narration = _esc(move.ref or move.narration or 'Credit Note')
    total_amount = abs(move.amount_total)

    entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>{total_amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    income_lines = move.line_ids.filtered(lambda l: l.display_type in ('product', False) and l.account_id.account_type in ('income', 'income_other', 'equity'))
    for line in income_lines:
        line_amt = abs(line.debit - line.credit)
        if line_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.sales_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{line_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    for tax_line in move.line_ids.filtered(lambda l: l.tax_line_id):
        tax_amt = abs(tax_line.debit - tax_line.credit)
        if tax_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.vat_output_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{tax_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="Credit Note" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>Credit Note</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PARTYLEDGERNAME>{partner_name}</PARTYLEDGERNAME>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_debit_note_xml(move, config):
    """Build Tally XML for Vendor Debit Note."""
    partner_name = _esc(move.partner_id.name or 'Cash Vendor')
    date_str = _tally_date(move.invoice_date or move.date)
    ref = _esc(move.name or '')
    narration = _esc(move.ref or move.narration or 'Debit Note')
    total_amount = abs(move.amount_total)

    entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>-{total_amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    expense_lines = move.line_ids.filtered(lambda l: l.display_type in ('product', False) and l.account_id.account_type in ('expense', 'expense_direct_cost', 'expense_depreciation'))
    for line in expense_lines:
        line_amt = abs(line.credit - line.debit)
        if line_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.purchase_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{line_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    for tax_line in move.line_ids.filtered(lambda l: l.tax_line_id):
        tax_amt = abs(tax_line.credit - tax_line.debit)
        if tax_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.vat_input_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{tax_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="Debit Note" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>Debit Note</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PARTYLEDGERNAME>{partner_name}</PARTYLEDGERNAME>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_expense_move_xml(move, config):
    """Build Tally XML for Expense / In Receipt entries."""
    date_str = _tally_date(move.invoice_date or move.date)
    ref = _esc(move.name or '')
    partner_name = _esc(move.partner_id.name or 'Cash')
    narration = _esc(move.ref or move.narration or move.name or 'Expense')
    total_amount = abs(move.amount_total)

    # 1. Partner credit (CREDIT = positive in Tally Accounting View)
    entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>{total_amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # 2. Expense lines (DEBIT = negative in Tally Accounting View)
    expense_lines = move.line_ids.filtered(lambda l: l.display_type in ('product', False) and l.account_id.account_type in ('expense', 'expense_direct_cost', 'expense_depreciation'))
    for line in expense_lines:
        line_amt = abs(line.debit - line.credit)
        if line_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.expense_ledger or line.account_id.name)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{line_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    # 3. Tax lines (DEBIT = negative in Tally Accounting View)
    tax_lines = move.line_ids.filtered(lambda l: l.tax_line_id)
    for tax_line in tax_lines:
        tax_amt = abs(tax_line.debit - tax_line.credit)
        if tax_amt > 0:
            entries += f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{_esc(config.vat_input_ledger)}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{tax_amt:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="Journal" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>Journal</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""


def build_payment_xml(payment, config):
    """
    Build Tally XML for an Odoo Payment (account.payment).

    Odoo payment types:
      - inbound  (customer pays us)  → Tally Receipt voucher
      - outbound (we pay vendor)     → Tally Payment voucher

    Receipt voucher (inbound):
      - Cash/Bank ledger:  ISDEEMEDPOSITIVE=Yes,  AMOUNT negative  (Debit)
      - Party ledger:      ISDEEMEDPOSITIVE=No,   AMOUNT positive  (Credit)

    Payment voucher (outbound):
      - Party ledger:      ISDEEMEDPOSITIVE=Yes,  AMOUNT negative  (Debit)
      - Cash/Bank ledger:  ISDEEMEDPOSITIVE=No,   AMOUNT positive  (Credit)
    """
    is_inbound = payment.payment_type == 'inbound'
    vch_type = 'Receipt' if is_inbound else 'Payment'

    partner_name = _esc(payment.partner_id.name or ('Cash Customer' if is_inbound else 'Cash Vendor'))
    date_str = _tally_date(payment.date)
    ref = _esc(payment.name or '')
    narration = _esc(payment.ref or payment.memo or payment.name or vch_type)
    amount = abs(payment.amount)

    # Determine the bank/cash ledger name
    # Use the journal name to map to the configured Tally ledger
    journal = payment.journal_id
    if journal.type == 'cash':
        bank_cash_ledger = _esc(config.cash_ledger or 'Cash')
    else:
        # Bank journal — use the journal name directly if it exists in Tally,
        # otherwise fall back to the configured bank_ledger
        bank_cash_ledger = _esc(journal.name or config.bank_ledger or 'Bank')

    if is_inbound:
        # Receipt: Bank/Cash debit, Party credit
        entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{bank_cash_ledger}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>-{amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""
    else:
        # Payment: Party debit, Bank/Cash credit
        entries = f"""
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{partner_name}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>Yes</ISPARTYLEDGER>
                        <AMOUNT>-{amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>
                    <ALLLEDGERENTRIES.LIST>
                        <LEDGERNAME>{bank_cash_ledger}</LEDGERNAME>
                        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
                        <ISPARTYLEDGER>No</ISPARTYLEDGER>
                        <AMOUNT>{amount:.2f}</AMOUNT>
                    </ALLLEDGERENTRIES.LIST>"""

    return f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Import</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>Vouchers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVCURRENTCOMPANY>{_esc(config.tally_company_name)}</SVCURRENTCOMPANY>
            </STATICVARIABLES>
        </DESC>
        <DATA>
            <TALLYMESSAGE xmlns:UDF="TallyUDF">
                <VOUCHER VCHTYPE="{vch_type}" ACTION="Create">
                    <DATE>{date_str}</DATE>
                    <VOUCHERTYPENAME>{vch_type}</VOUCHERTYPENAME>
                    <VOUCHERNUMBER>{ref}</VOUCHERNUMBER>
                    <PARTYLEDGERNAME>{partner_name}</PARTYLEDGERNAME>
                    <PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>
                    <NARRATION>{narration}</NARRATION>
                    {entries}
                </VOUCHER>
            </TALLYMESSAGE>
        </DATA>
    </BODY>
</ENVELOPE>"""
