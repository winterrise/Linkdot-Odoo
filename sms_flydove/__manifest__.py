{
    'name': 'SMS via Flydove (flydove.net)',
    'version': '18.0.1.0.0',
    'category': 'Hidden/Tools',
    'summary': 'Send Odoo SMS through Flydove (飛信資訊) SmartDove transactional SMS API instead of Odoo IAP',
    'license': 'LGPL-3',
    'depends': ['sms'],
    'external_dependencies': {'python': []},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
