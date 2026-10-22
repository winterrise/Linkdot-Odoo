from odoo import fields, models

from ..tools.flydove_api import DEFAULT_ENDPOINT


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    flydove_sms_provider = fields.Selection(
        [('iap', 'Odoo (IAP credits)'), ('flydove', 'Flydove (flydove.net)')],
        string='SMS Provider', config_parameter='sms_flydove.provider', default='iap',
        groups='base.group_system')
    flydove_api_token = fields.Char(
        'Flydove API Token', config_parameter='sms_flydove.token', groups='base.group_system',
        help='Admin API Token from https://console2.flydove.net/apis')
    flydove_api_endpoint = fields.Char(
        'Flydove API Endpoint', config_parameter='sms_flydove.endpoint', groups='base.group_system',
        default=DEFAULT_ENDPOINT)
