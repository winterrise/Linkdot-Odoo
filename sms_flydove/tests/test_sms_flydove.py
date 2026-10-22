import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.sms_flydove.tools.flydove_api import to_e164

REQUEST = 'odoo.addons.sms_flydove.tools.flydove_api.requests.request'


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


@tagged('post_install', '-at_install')
class TestSmsFlydove(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('sms_flydove.provider', 'flydove')
        set_param('sms_flydove.token', 'test-token')
        cls.partner = cls.env['res.partner'].create({'name': 'Donor', 'mobile': '+886912345678'})

    def _post_sms(self, number='+886912345678'):
        """Post an SMS on a partner chatter; returns its mail.notification."""
        message = self.partner._message_sms('Thank you', sms_numbers=[number])
        return self.env['mail.notification'].search([('mail_message_id', '=', message.id)])

    def test_to_e164(self):
        self.assertEqual(to_e164('+886 912-345-678'), '+886912345678')
        self.assertEqual(to_e164('0912345678'), '+886912345678')
        self.assertEqual(to_e164('00886912345678'), '+886912345678')
        self.assertEqual(to_e164('+8860912345678'), '+886912345678')
        self.assertFalse(to_e164('12345'))
        self.assertFalse(to_e164(False))

    def test_send_success_then_delivered(self):
        with patch(REQUEST, return_value=FakeResponse(200, {'batch_id': 'B1'})) as mock:
            notification = self._post_sms()
        method, url = mock.call_args.args
        kwargs = mock.call_args.kwargs
        self.assertEqual((method, url), ('POST', 'https://clientapi.flydove.net/api/v1/transactional_sms'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-token')
        self.assertEqual(kwargs['json'], {'content': 'Thank you', 'destinations': [{'to': '+886912345678'}]})
        self.assertEqual(notification.notification_status, 'pending')

        message = self.env['sms.flydove.message'].search([('batch_id', '=', 'B1')])
        self.assertEqual(message.number, '886912345678')
        self.assertEqual(message.state, 'pending')

        # still at the carrier: nothing final yet
        with patch(REQUEST, return_value=FakeResponse(200, {
                'data': [{'to': '886912345678', 'code': 2001, 'description': '已送達業者'}],
                'meta': {'next_page': None}})):
            self.env['sms.flydove.message']._cron_poll_delivery()
        self.assertEqual(message.state, 'pending')
        self.assertEqual(notification.notification_status, 'pending')

        with patch(REQUEST, return_value=FakeResponse(200, {
                'data': [{'to': '886912345678', 'code': 2002, 'description': '已送達手機'}],
                'meta': {'next_page': None}})) as mock:
            self.env['sms.flydove.message']._cron_poll_delivery()
        self.assertEqual(mock.call_args.kwargs['params']['batch_id'], 'B1')
        self.assertEqual(message.state, 'done')
        self.assertEqual(message.flydove_code, 2002)
        self.assertEqual(notification.notification_status, 'sent')

    def test_delivery_failure_bounces(self):
        with patch(REQUEST, return_value=FakeResponse(200, {'batch_id': 'B2'})):
            notification = self._post_sms()
        with patch(REQUEST, return_value=FakeResponse(200, {
                'data': [{'to': '886912345678', 'code': 4001, 'description': '無效的手機號碼'}],
                'meta': {'next_page': None}})):
            self.env['sms.flydove.message']._cron_poll_delivery()
        self.assertEqual(notification.notification_status, 'bounce')
        self.assertEqual(notification.failure_type, 'sms_invalid_destination')

    def test_bad_token(self):
        with patch(REQUEST, return_value=FakeResponse(401, {'message': 'Unauthenticated.'})):
            notification = self._post_sms()
        self.assertEqual(notification.notification_status, 'exception')
        self.assertEqual(notification.failure_type, 'sms_acc')
        self.assertFalse(self.env['sms.flydove.message'].search([]))

    def test_flydove_without_token_fails_instead_of_iap(self):
        self.env['ir.config_parameter'].sudo().set_param('sms_flydove.token', False)
        with patch(REQUEST) as mock_flydove, \
                patch('odoo.addons.sms.tools.sms_api.SmsApi._send_sms_batch') as mock_iap:
            notification = self._post_sms()
        mock_flydove.assert_not_called()
        mock_iap.assert_not_called()
        self.assertEqual(notification.failure_type, 'sms_acc')

    def test_invalid_number_not_sent(self):
        with patch(REQUEST) as mock:
            notification = self._post_sms(number='12345')
        mock.assert_not_called()
        self.assertEqual(notification.notification_status, 'exception')
        self.assertEqual(notification.failure_type, 'sms_number_format')

    def test_disabled_falls_back_to_iap(self):
        self.env['ir.config_parameter'].sudo().set_param('sms_flydove.provider', 'iap')
        with patch(REQUEST) as mock_flydove, \
                patch('odoo.addons.sms.tools.sms_api.SmsApi._send_sms_batch', return_value=[]) as mock_iap:
            self._post_sms()
        mock_flydove.assert_not_called()
        mock_iap.assert_called_once()
