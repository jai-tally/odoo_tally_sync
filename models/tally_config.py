# -*- coding: utf-8 -*-
"""
Tally Configuration Settings
Stores the TallyPrime gateway connection details and company mapping.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)


class TallyConfig(models.Model):
    _name = 'tally.config'
    _description = 'TallyPrime Gateway Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Odoo Company',
        required=True, ondelete='cascade',
        default=lambda self: self.env.company,
    )
    tally_company_name = fields.Char(
        string='TallyPrime Company Name',
        required=True,
        help='Exact company name as it appears inside TallyPrime (case-sensitive).',
    )
    tally_host = fields.Char(
        string='Tally Host',
        default='localhost',
        required=True,
        help='IP/hostname where TallyPrime is running. Use "localhost" if on same machine.',
    )
    tally_port = fields.Integer(
        string='Tally Port',
        default=9000,
        required=True,
        help='Port configured in TallyPrime Gateway (default: 9000).',
    )
    timeout = fields.Integer(
        string='Request Timeout (seconds)',
        default=30,
        help='How long to wait for TallyPrime to respond before marking as failed.',
    )
    active = fields.Boolean(default=True)

    # Ledger mapping for UAE VAT
    purchase_ledger = fields.Char(
        string='Purchase Ledger Name (Tally)',
        default='Purchase Account',
        help='Exact ledger name in Tally for purchase accounts.',
    )
    sales_ledger = fields.Char(
        string='Sales Ledger Name (Tally)',
        default='Sales Account',
        help='Exact ledger name in Tally for sales accounts.',
    )
    expense_ledger = fields.Char(
        string='Expense Ledger Name (Tally)',
        default='Indirect Expenses',
        help='Exact ledger name in Tally for expense postings.',
    )
    vat_input_ledger = fields.Char(
        string='Input VAT 5% Ledger (Tally)',
        default='Input VAT 5%',
    )
    vat_output_ledger = fields.Char(
        string='Output VAT 5% Ledger (Tally)',
        default='Output VAT 5%',
    )
    default_godown = fields.Char(
        string='Default Godown/Location (Tally)',
        default='Main Location',
        help='Default stock location name in TallyPrime for inventory entries.',
    )

    # Discount & Round-Off ledgers
    discount_allowed_ledger = fields.Char(
        string='Sales Discount Ledger (Tally)',
        default='Discount Allowed',
        help='Tally ledger for sales-side discounts (under Indirect Expenses). Auto-created if missing.',
    )
    discount_received_ledger = fields.Char(
        string='Purchase Discount Ledger (Tally)',
        default='Discount Received',
        help='Tally ledger for purchase-side discounts (under Indirect Income). Auto-created if missing.',
    )
    round_off_ledger = fields.Char(
        string='Round Off Ledger (Tally)',
        default='Round Off',
        help='Tally ledger for cash rounding differences (under Indirect Expenses). Auto-created if missing.',
    )

    # Payment ledgers (bank / cash accounts)
    cash_ledger = fields.Char(
        string='Cash Ledger (Tally)',
        default='Cash',
        help='Tally ledger name for the Cash account used in Receipt/Payment vouchers.',
    )
    bank_ledger = fields.Char(
        string='Bank Ledger (Tally)',
        default='Bank',
        help='Tally ledger name for the Bank account used in Receipt/Payment vouchers.',
    )

    # Retry configuration
    max_retries = fields.Integer(
        string='Max Auto-Retry Attempts',
        default=3,
        help='Number of times the system will auto-retry failed pushes via the scheduled cron.',
    )

    _company_uniq = models.Constraint(
        'unique(company_id)',
        'Only one Tally configuration per company is allowed.',
    )

    def get_tally_url(self):
        """Return the full TallyPrime gateway URL."""
        self.ensure_one()
        return f"http://{self.tally_host}:{self.tally_port}"

    def test_connection(self):
        """Send a simple export request to verify connectivity with TallyPrime."""
        self.ensure_one()
        xml_ping = f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Data</TYPE>
        <ID>List of Companies</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
        </DESC>
    </BODY>
</ENVELOPE>"""
        try:
            response = requests.post(
                self.get_tally_url(),
                data=xml_ping.encode('utf-8'),
                headers={'Content-Type': 'text/xml; charset=utf-8'},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('TallyPrime responded on %s. Ready to sync.') % self.get_tally_url(),
                        'sticky': False,
                        'type': 'success',
                    },
                }
            else:
                raise UserError(_('TallyPrime returned HTTP %s. Check if Tally is open and company is loaded.') % response.status_code)
        except requests.exceptions.ConnectionError:
            raise UserError(_(
                'Cannot connect to TallyPrime at %s.\n\n'
                'Please ensure:\n'
                '1. TallyPrime is open on this machine.\n'
                '2. A company is loaded in Tally.\n'
                '3. ODBC/XML Server is enabled in Tally (Gateway → F1 Help → Settings → Connectivity).\n'
                '4. Port %s is not blocked by firewall.'
            ) % (self.get_tally_url(), self.tally_port))
        except requests.exceptions.Timeout:
            raise UserError(_('Connection to TallyPrime timed out after %s seconds.') % self.timeout)

