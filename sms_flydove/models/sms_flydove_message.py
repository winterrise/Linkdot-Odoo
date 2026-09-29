import logging
from datetime import timedelta

from odoo import api, fields, models

from ..tools.flydove_api import CODE_DELIVERED, CODES_FAILED, FlydoveApiError, digits_only

_logger = logging.getLogger(__name__)

POLL_MAX_AGE = timedelta(days=3)


class SmsFlydoveMessage(models.Model):
    """One SMS handed to Flydove, kept until its delivery status is final.

    Flydove has no delivery webhook for transactional SMS, so a cron polls the
    batch status and updates the sms.tracker (chatter notifications, SMS
    marketing traces) the same way the IAP webhook /sms/status would.
    sms.sms records themselves are garbage-collected once sent, hence the uuid.
    """
    _name = 'sms.flydove.message'
    _description = 'SMS sent through Flydove'
    _order = 'id desc'

    batch_id = fields.Char(required=True, index=True, readonly=True)
    sms_uuid = fields.Char('SMS UUID', required=True, index=True, readonly=True)
    number = fields.Char(required=True, readonly=True, help='Digits only, as returned by the Flydove query API')
    state = fields.Selection(
        [('pending', 'Waiting for delivery report'), ('done', 'Final')],
        default='pending', required=True, index=True)
    flydove_code = fields.Integer(readonly=True)
    flydove_description = fields.Char(readonly=True)

    @api.model
    def _cron_poll_delivery(self):
        api_client = self.env['sms.sms']._flydove_api()
        pending = self.search([('state', '=', 'pending')])
        if not pending:
            return
        too_old = pending.filtered(lambda m: m.create_date < fields.Datetime.now() - POLL_MAX_AGE)
        too_old.write({'state': 'done'})
        pending -= too_old
        if api_client is None:
            return
        for batch_id, messages in pending.grouped('batch_id').items():
            try:
                statuses = api_client.get_batch_statuses(batch_id)
            except FlydoveApiError as e:
                _logger.warning('Flydove: cannot poll batch %s: %s', batch_id, e)
                continue
            messages._flydove_apply_statuses(statuses)

    def _flydove_apply_statuses(self, statuses):
        by_number = self.grouped('number')
        for status in statuses:
            messages = by_number.get(digits_only(status.get('to')))
            code = status.get('code')
            if not messages or code is None:
                continue
            code = int(code)
            messages.write({'flydove_code': code, 'flydove_description': status.get('description')})
            trackers = self.env['sms.tracker'].sudo().search([('sms_uuid', 'in', messages.mapped('sms_uuid'))])
            if code == CODE_DELIVERED:
                trackers._action_update_from_sms_state('sent')
            elif code in CODES_FAILED:
                trackers._action_update_from_provider_error(CODES_FAILED[code])
            else:
                continue  # still queued / sending / at the carrier
            messages.state = 'done'
