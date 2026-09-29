import logging

from odoo import models, tools

from ..tools.flydove_api import MAX_DESTINATIONS, FlydoveApiError, FlydoveSmsApi, digits_only, to_e164

_logger = logging.getLogger(__name__)


class SmsSms(models.Model):
    _inherit = 'sms.sms'

    def _flydove_api(self):
        """Return a configured FlydoveSmsApi, or None when the selected provider is Odoo IAP."""
        get_param = self.env['ir.config_parameter'].sudo().get_param
        if get_param('sms_flydove.provider') != 'flydove':
            return None
        # a missing token fails the SMS (sms_acc) rather than silently falling back to IAP
        return FlydoveSmsApi(get_param('sms_flydove.token'), endpoint=get_param('sms_flydove.endpoint'))

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        api = self._flydove_api()
        if api is None:
            return super()._send(unlink_failed=unlink_failed, unlink_sent=unlink_sent, raise_exception=raise_exception)

        results = []  # same shape as IAP results: [{'uuid': str, 'state': str}]
        message_vals = []
        for body, body_sms in self.grouped('body').items():
            valid_sms = self.browse()
            for sms in body_sms:
                if to_e164(sms.number):
                    valid_sms |= sms
                else:
                    results.append({'uuid': sms.uuid, 'state': 'wrong_number_format'})
            for chunk_ids in tools.split_every(MAX_DESTINATIONS, valid_sms.ids):
                chunk = self.browse(chunk_ids)
                try:
                    batch_id = api.send(body, [to_e164(sms.number) for sms in chunk])
                except FlydoveApiError as e:
                    _logger.info('Flydove: batch of %s SMS %s failed: %s', len(chunk), chunk.ids, e)
                    if raise_exception:
                        raise
                    results += [{'uuid': sms.uuid, 'state': e.state} for sms in chunk]
                    continue
                _logger.info('Flydove: sent %s SMS %s as batch %s', len(chunk), chunk.ids, batch_id)
                results += [{'uuid': sms.uuid, 'state': 'success'} for sms in chunk]
                message_vals += [{
                    'batch_id': batch_id,
                    'sms_uuid': sms.uuid,
                    'number': digits_only(to_e164(sms.number)),
                } for sms in chunk]

        if message_vals:
            self.env['sms.flydove.message'].sudo().create(message_vals)
        self._flydove_apply_send_results(results, unlink_failed=unlink_failed, unlink_sent=unlink_sent)

    def _flydove_apply_send_results(self, results, unlink_failed=False, unlink_sent=True):
        """Same post-processing as sms.sms._send in Odoo 18.0 (addons/sms/models/sms_sms.py)."""
        results_uuids = [result['uuid'] for result in results]
        all_sms_sudo = self.env['sms.sms'].sudo().search(
            [('uuid', 'in', results_uuids)]).with_context(sms_skip_msg_notification=True)

        for iap_state, results_group in tools.groupby(results, key=lambda result: result['state']):
            uuids = {result['uuid'] for result in results_group}
            sms_sudo = all_sms_sudo.filtered(lambda s: s.uuid in uuids)
            if success_state := self.IAP_TO_SMS_STATE_SUCCESS.get(iap_state):
                sms_sudo.sms_tracker_id._action_update_from_sms_state(success_state)
                to_delete = {'to_delete': True} if unlink_sent else {}
                sms_sudo.write({'state': success_state, 'failure_type': False, **to_delete})
            else:
                failure_type = self.IAP_TO_SMS_FAILURE_TYPE.get(iap_state, 'unknown')
                if failure_type != 'unknown':
                    sms_sudo.sms_tracker_id._action_update_from_sms_state('error', failure_type=failure_type)
                else:
                    sms_sudo.sms_tracker_id._action_update_from_provider_error(iap_state)
                to_delete = {'to_delete': True} if unlink_failed else {}
                sms_sudo.write({'state': 'error', 'failure_type': failure_type, **to_delete})

        all_sms_sudo.mail_message_id._notify_message_notification_update()
