from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

OFFICER_GROUP = 'linkdot_health_check.group_health_check_officer'


class ResCompany(models.Model):
    _inherit = 'res.company'

    health_check_officer_id = fields.Many2one(
        'res.users', string='Health Check Officer',
        domain=lambda self: self._domain_health_check_officer_id(),
        help="Receives reminders for due health checks and abnormal-result follow-ups. "
             "Must be a Health Check Officer, otherwise the reminders cannot be opened.")

    @api.model
    def _domain_health_check_officer_id(self):
        group = self.env.ref(OFFICER_GROUP, raise_if_not_found=False)
        return [('share', '=', False)] + ([('groups_id', 'in', group.id)] if group else [])

    @api.constrains('health_check_officer_id')
    def _check_health_check_officer_id(self):
        for company in self:
            officer = company.health_check_officer_id
            if officer and not officer.has_group(OFFICER_GROUP):
                raise ValidationError(_(
                    "%s cannot be the health check officer: give them the Health Checks "
                    "'Officer' or 'Administrator' access right first.", officer.name))
