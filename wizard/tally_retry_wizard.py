# -*- coding: utf-8 -*-
"""Retry Wizard: Bulk-retry or bulk-skip failed Tally sync logs."""
from odoo import models, fields, api, _


class TallyRetryWizard(models.TransientModel):
    _name = 'tally.retry.wizard'
    _description = 'TallyPrime Sync Retry Wizard'

    log_ids = fields.Many2many(
        'tally.sync.log',
        string='Failed Logs to Retry',
        default=lambda self: self.env['tally.sync.log'].search([('state', '=', 'failed')]),
    )
    action = fields.Selection([
        ('retry', 'Retry All Failed'),
        ('skip', 'Mark All as Skipped'),
    ], string='Action', default='retry', required=True)

    def execute(self):
        if self.action == 'retry':
            for log in self.log_ids.filtered(lambda l: l.state == 'failed'):
                if log.move_id:
                    log.move_id._push_to_tally(force=True)
        elif self.action == 'skip':
            self.log_ids.filtered(lambda l: l.state == 'failed').write({'state': 'skipped'})
        return {'type': 'ir.actions.act_window_close'}
