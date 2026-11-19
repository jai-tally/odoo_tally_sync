# -*- coding: utf-8 -*-
"""
account.payment Extension — Real-Time Push to TallyPrime
Hooks into the payment confirmation workflow to push Receipt/Payment vouchers.
Covers: Customer receipts (inbound) and Vendor payments (outbound).
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .tally_client import TallyClient
from .tally_xml_builder import build_payment_xml, build_ledger_xml
import logging

_logger = logging.getLogger(__name__)

# Odoo payment_type → Tally document type label
PAYMENT_TYPE_MAP = {
    'inbound': 'receipt',
    'outbound': 'payment',
}


class AccountPayment(models.Model):
    _inherit = 'account.payment'

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

    # ── Hook: Override action_post() ─────────────────────────────────────────
    def action_post(self):
        """Override posting to trigger Tally push after successful confirmation."""
        result = super().action_post()
        for payment in self.filtered(lambda p: p.state == 'posted'):
            payment._push_to_tally()
        return result

    # ── Core Push Logic ───────────────────────────────────────────────────────
    def _push_to_tally(self, force=False):
        """
        Build XML and push this payment to TallyPrime.
        :param force: If True, retry even if already synced.
        """
        self.ensure_one()

        if self.payment_type not in PAYMENT_TYPE_MAP:
            return  # Only handle inbound/outbound

        if self.state != 'posted':
            return  # Only push confirmed payments

        if self.tally_sync_status == 'synced' and not force:
            return  # Already synced, skip unless forced

        config = self._get_tally_config()
        if not config:
            _logger.warning(
                'No TallyPrime config found for company %s. Skipping payment sync.',
                self.company_id.name,
            )
            return

        # Ensure partner and bank/cash ledgers exist in Tally
        self._ensure_payment_ledgers(config)

        # Build XML payload
        xml_payload = build_payment_xml(self, config)
        if not xml_payload:
            self.write({'tally_sync_status': 'skipped'})
            return

        # Send to Tally
        client = TallyClient(config.get_tally_url(), timeout=config.timeout)
        success, response_text, error_msg = client.send(xml_payload)

        # Update sync status
        now = fields.Datetime.now()
        doc_type = PAYMENT_TYPE_MAP[self.payment_type]
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

        # Write sync log
        self._create_payment_sync_log(doc_type, xml_payload, response_text, success, error_msg)

    def _get_tally_config(self):
        """Fetch the TallyPrime config for the current company."""
        config = self.env['tally.config'].search(
            [('company_id', '=', self.company_id.id), ('active', '=', True)],
            limit=1,
        )
        return config or None

    def _ensure_payment_ledgers(self, config):
        """
        Auto-create the partner ledger and the bank/cash ledger in Tally
        before pushing the payment voucher.
        """
        client = TallyClient(config.get_tally_url(), timeout=config.timeout)

        # Partner ledger
        if self.partner_id:
            if self.payment_type == 'inbound':
                parent_group = 'Sundry Debtors'
            else:
                parent_group = 'Sundry Creditors'
            partner_xml = build_ledger_xml(
                tally_company=config.tally_company_name,
                ledger_name=self.partner_id.name,
                parent_group=parent_group,
            )
            client.send(partner_xml)

        # Bank / Cash ledger
        journal = self.journal_id
        if journal.type == 'cash':
            ledger_name = config.cash_ledger or 'Cash'
            parent_group = 'Cash-in-Hand'
        else:
            ledger_name = journal.name or config.bank_ledger or 'Bank'
            parent_group = 'Bank Accounts'

        bank_xml = build_ledger_xml(
            tally_company=config.tally_company_name,
            ledger_name=ledger_name,
            parent_group=parent_group,
        )
        client.send(bank_xml)

    def _create_payment_sync_log(self, doc_type, xml_payload, response_text, success, error_msg):
        """Write a log record for this payment sync attempt."""
        self.env['tally.sync.log'].sudo().create({
            'document_ref': self.name,
            'document_type': doc_type,
            'payment_id': self.id,
            'company_id': self.company_id.id,
            'state': 'success' if success else 'failed',
            'retry_count': self.tally_sync_count,
            'xml_payload': xml_payload,
            'tally_response': response_text[:5000] if response_text else '',
            'error_message': error_msg,
            'synced_at': fields.Datetime.now() if success else False,
        })

    # ── Manual Sync Button ────────────────────────────────────────────────────
    def action_sync_to_tally(self):
        """Button: manually push/re-push this payment to TallyPrime."""
        for payment in self:
            if payment.state != 'posted':
                raise UserError(_('Only confirmed/posted payments can be synced to TallyPrime.'))
            payment._push_to_tally(force=True)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tally Sync'),
                'message': _('Payment sync attempted. Check the Tally Status field or Sync Logs for result.'),
                'sticky': False,
                'type': 'info',
            },
        }

    def action_view_tally_logs(self):
        """Button: open Tally Sync Logs for this payment."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tally Sync Logs'),
            'res_model': 'tally.sync.log',
            'view_mode': 'list,form',
            'domain': [('payment_id', '=', self.id)],
            'context': {'default_payment_id': self.id},
        }
