# -*- coding: utf-8 -*-
"""
account.move Extension — Real-Time Push to TallyPrime
Hooks into the invoice/bill posting workflow to push to Tally on confirmation.
Covers: Sales Invoice, Purchase Bill, Credit Note, Debit Note, Expense Receipts.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .tally_client import TallyClient
from .tally_xml_builder import (
    build_sales_xml, build_purchase_xml,
    build_credit_note_xml, build_debit_note_xml,
    build_expense_move_xml, build_ledger_xml,
)
import logging

_logger = logging.getLogger(__name__)

# Map Odoo move_type → document type label
MOVE_TYPE_MAP = {
    'out_invoice': 'sale',
    'in_invoice': 'purchase',
    'out_refund': 'credit_note',
    'in_refund': 'debit_note',
    'in_receipt': 'expense',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ── Tally Sync Status Fields ──────────────────────────────────────────────
    tally_sync_status = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced ✓'),
        ('failed', 'Failed ✗'),
        ('skipped', 'Skipped'),
    ], string='Tally Status', default='not_synced', copy=False, readonly=True, index=True)

    tally_synced_at = fields.Datetime(string='Tally Synced At', readonly=True, copy=False)
    tally_error = fields.Text(string='Tally Sync Error', readonly=True, copy=False)
    tally_sync_count = fields.Integer(string='Sync Attempts', default=0, readonly=True, copy=False)

    # ── Hook: Override _post() ────────────────────────────────────────────────
    def _post(self, soft=True):
        """Override posting to trigger Tally push after successful confirmation."""
        result = super()._post(soft=soft)

        # Filter only the move types we care about
        target_moves = self.filtered(
            lambda m: m.move_type in MOVE_TYPE_MAP and m.state == 'posted'
        )
        for move in target_moves:
            move._push_to_tally()

        return result

    # ── Core Push Logic ───────────────────────────────────────────────────────
    def _push_to_tally(self, force=False):
        """
        Build XML and push this journal entry to TallyPrime.
        :param force: If True, retry even if already synced.
        """
        self.ensure_one()

        if self.move_type not in MOVE_TYPE_MAP:
            return  # Not a supported document type

        if self.state != 'posted':
            return  # Only push confirmed entries

        if self.tally_sync_status == 'synced' and not force:
            return  # Already synced, skip unless forced

        config = self._get_tally_config()
        if not config:
            _logger.warning('No TallyPrime config found for company %s. Skipping sync.', self.company_id.name)
            return

        # Ensure partner ledger exists in Tally before pushing voucher
        self._ensure_partner_ledger(config)
        self._ensure_discount_roundoff_ledgers(config)

        # Build the appropriate XML payload
        doc_type = MOVE_TYPE_MAP[self.move_type]
        xml_payload = self._build_xml(config)

        if not xml_payload:
            self.write({'tally_sync_status': 'skipped'})
            return

        # Send to Tally
        client = TallyClient(config.get_tally_url(), timeout=config.timeout)
        success, response_text, error_msg = client.send(xml_payload)

        # Update sync state on the record
        now = fields.Datetime.now()
        if success:
            self.write({
                'tally_sync_status': 'synced',
                'tally_synced_at': now,
                'tally_error': False,
                'tally_sync_count': self.tally_sync_count + 1,
            })
        else:
            self.write({
                'tally_sync_status': 'failed',
                'tally_error': error_msg,
                'tally_sync_count': self.tally_sync_count + 1,
            })

        # Log the attempt
        self._create_sync_log(doc_type, xml_payload, response_text, success, error_msg)

    def _build_xml(self, config):
        """Dispatch to correct XML builder based on move type."""
        builders = {
            'out_invoice': build_sales_xml,
            'in_invoice': build_purchase_xml,
            'out_refund': build_credit_note_xml,
            'in_refund': build_debit_note_xml,
            'in_receipt': build_expense_move_xml,
        }
        builder = builders.get(self.move_type)
        if not builder:
            return None
        return builder(self, config)

    def _get_tally_config(self):
        """Fetch the TallyPrime config for the current company."""
        config = self.env['tally.config'].search(
            [('company_id', '=', self.company_id.id), ('active', '=', True)],
            limit=1,
        )
        return config or None

    def _ensure_discount_roundoff_ledgers(self, config):
        """
        Auto-create Discount Allowed, Discount Received, and Round Off ledgers
        in TallyPrime before the voucher push, to prevent missing-ledger errors.
        Only creates if the invoice actually has discounts or rounding.
        """
        client = TallyClient(config.get_tally_url(), timeout=config.timeout)

        # Check if any product line has a discount
        has_discount = any(
            l.discount and l.discount > 0
            for l in self.line_ids
            if l.display_type in ('product', False)
        )

        if has_discount:
            if self.move_type in ('out_invoice', 'out_refund'):
                # Sales discount → Discount Allowed under Indirect Expenses
                ledger_xml = build_ledger_xml(
                    tally_company=config.tally_company_name,
                    ledger_name=config.discount_allowed_ledger,
                    parent_group='Indirect Expenses',
                )
                client.send(ledger_xml)
            elif self.move_type in ('in_invoice', 'in_refund'):
                # Purchase discount → Discount Received under Indirect Income
                ledger_xml = build_ledger_xml(
                    tally_company=config.tally_company_name,
                    ledger_name=config.discount_received_ledger,
                    parent_group='Indirect Income',
                )
                client.send(ledger_xml)

        # Check if there is a cash rounding line
        if self.invoice_cash_rounding_id:
            ledger_xml = build_ledger_xml(
                tally_company=config.tally_company_name,
                ledger_name=config.round_off_ledger,
                parent_group='Indirect Expenses',
            )
            client.send(ledger_xml)

    def _ensure_partner_ledger(self, config):
        """
        Auto-create the partner as a Ledger in TallyPrime before the voucher push.
        This prevents import failures due to missing ledger masters.
        """
        if not self.partner_id:
            return

        partner_name = self.partner_id.name
        # Determine parent group in Tally
        if self.move_type in ('out_invoice', 'out_refund'):
            parent_group = 'Sundry Debtors'
        elif self.move_type == 'in_receipt':
            parent_group = 'Loans & Advances (Asset)'
        else:
            parent_group = 'Sundry Creditors'

        ledger_xml = build_ledger_xml(
            tally_company=config.tally_company_name,
            ledger_name=partner_name,
            parent_group=parent_group,
        )
        client = TallyClient(config.get_tally_url(), timeout=config.timeout)
        client.send(ledger_xml)  # Ignore failure here; voucher push will catch the real error

    def _create_sync_log(self, doc_type, xml_payload, response_text, success, error_msg):
        """Write a log record for this sync attempt."""
        self.env['tally.sync.log'].sudo().create({
            'document_ref': self.name,
            'document_type': doc_type,
            'move_id': self.id,
            'company_id': self.company_id.id,
            'state': 'success' if success else 'failed',
            'retry_count': self.tally_sync_count,
            'xml_payload': xml_payload,
            'tally_response': response_text[:5000] if response_text else '',
            'error_message': error_msg,
            'synced_at': fields.Datetime.now() if success else False,
        })

    # ── Manual Sync Button Action ─────────────────────────────────────────────
    def action_sync_to_tally(self):
        """Button: manually push/re-push this invoice to TallyPrime."""
        for move in self:
            if move.state != 'posted':
                raise UserError(_('Only confirmed/posted entries can be synced to TallyPrime.'))
            move._push_to_tally(force=True)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tally Sync'),
                'message': _('Sync attempted. Check the Tally Status field or Sync Logs for result.'),
                'sticky': False,
                'type': 'info',
            },
        }

    def action_view_tally_logs(self):
        """Button: open Tally Sync Logs for this invoice."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tally Sync Logs'),
            'res_model': 'tally.sync.log',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }
