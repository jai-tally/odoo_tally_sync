# -*- coding: utf-8 -*-
"""
Tally Sync Log
Tracks every push attempt to TallyPrime: status, payload, response, retries.
"""
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

SYNC_STATES = [
    ('pending', 'Pending'),
    ('success', 'Synced'),
    ('failed', 'Failed'),
    ('skipped', 'Skipped'),
]


class TallySyncLog(models.Model):
    _name = 'tally.sync.log'
    _description = 'TallyPrime Sync Log'
    _order = 'create_date desc'
    _rec_name = 'document_ref'

    document_ref = fields.Char(string='Document Reference', readonly=True)
    document_type = fields.Selection([
        ('sale', 'Sales Invoice'),
        ('purchase', 'Purchase Bill'),
        ('credit_note', 'Credit Note'),
        ('debit_note', 'Debit Note'),
        ('expense', 'Expense Receipt / Entry'),
        ('receipt', 'Customer Receipt'),
        ('payment', 'Vendor Payment'),
    ], string='Document Type', readonly=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', ondelete='set null', readonly=True)
    payment_id = fields.Many2one('account.payment', string='Payment', ondelete='set null', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    state = fields.Selection(SYNC_STATES, string='Sync Status', default='pending', readonly=True, index=True)
    retry_count = fields.Integer(string='Retry Count', default=0, readonly=True)
    xml_payload = fields.Text(string='XML Sent to Tally', readonly=True)
    tally_response = fields.Text(string='Tally Response', readonly=True)
    error_message = fields.Text(string='Error / Exception', readonly=True)
    synced_at = fields.Datetime(string='Synced At', readonly=True)
    create_date = fields.Datetime(string='Created At', readonly=True)

    def action_retry(self):
        """Manual retry button on the log record."""
        for log in self:
            if log.state == 'failed':
                if log.move_id:
                    log.move_id._push_to_tally(force=True)
                elif log.payment_id:
                    log.payment_id._push_to_tally(force=True)

    def action_mark_skipped(self):
        """Mark a failed log as skipped so cron ignores it."""
        self.write({'state': 'skipped'})

    @api.model
    def cron_retry_failed(self):
        """
        Scheduled cron: retry failed sync logs.
        Only retries moves that are NOT yet synced.
        """
        configs = self.env['tally.config'].search([('active', '=', True)])
        max_retries_map = {c.company_id.id: c.max_retries for c in configs}

        failed_logs = self.search([
            ('state', '=', 'failed'),
            ('retry_count', '<', 5),
        ])
        for log in failed_logs:
            # If the underlying record is already synced, mark log as skipped
            if log.move_id and log.move_id.tally_sync_status == 'synced':
                log.write({'state': 'skipped'})
                continue
            if log.payment_id and log.payment_id.tally_sync_status == 'synced':
                log.write({'state': 'skipped'})
                continue

            company_max = max_retries_map.get(log.company_id.id, 3)
            if log.retry_count >= company_max:
                continue

            if log.move_id:
                log.move_id._push_to_tally(force=False)
            elif log.payment_id:
                log.payment_id._push_to_tally(force=False)
