from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    health_check_reminder_days = fields.Integer(
        string='Remind Days Before Due', default=60,
        config_parameter='linkdot_health_check.reminder_days')
