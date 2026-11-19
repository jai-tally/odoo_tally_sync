# -*- coding: utf-8 -*-
{
    'name': 'Odoo ↔ TallyPrime Real-Time Sync',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Integrations',
    'summary': 'Real-time push of Sales, Purchase, Credit Note, Debit Note, Expenses & Payments to TallyPrime via XML gateway',
    'description': """
        Automatically pushes confirmed/validated accounting entries from Odoo Community
        to TallyPrime via its built-in HTTP/XML gateway (port 9000).

        Supported document types:
        - Customer Invoice (Sales)
        - Vendor Bill (Purchase)
        - Customer Credit Note
        - Vendor Debit Note (Refund)
        - Expenses (Direct / Receipts / Vendor Bills)
        - Customer Receipts (Receipt vouchers)
        - Vendor Payments (Payment vouchers)

        Features:
        - Real-time push on document confirmation
        - Retry queue for failed pushes
        - Manual re-sync button on each document
        - Sync log model to track all pushes
        - UAE VAT support (Standard 5%, Zero-rated, Exempt)
        - Discount Allowed / Discount Received sync
        - Cash Rounding / Round Off sync
        - Ledger auto-creation in Tally before voucher push
    """,
    'author': 'Custom',
    'depends': [
        'account',
        'base',
    ],
    'data': [
        'security/ir.access.csv',
        'data/tally_sync_cron.xml',
        'views/tally_config_views.xml',
        'views/tally_sync_log_views.xml',
        'views/account_move_views.xml',
        'views/account_payment_views.xml',
        'wizard/tally_retry_wizard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
