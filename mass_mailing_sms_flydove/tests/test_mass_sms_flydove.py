from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.sms_flydove.tests.test_sms_flydove import REQUEST, FakeResponse


@tagged('post_install', '-at_install')
class TestMassSmsFlydove(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        set_param = cls.env['ir.config_parameter'].sudo().set_param
        set_param('sms_flydove.provider', 'flydove')
        set_param('sms_flydove.token', 'test-token')
        cls.partners = cls.env['res.partner'].create([
            {'name': 'Donor A', 'mobile': '+886912345678'},
            {'name': 'Donor B', 'mobile': '+886987654321'},
        ])
        cls.mailing = cls.env['mailing.mailing'].create({
            'name': 'Year-end appeal',
            'subject': 'Year-end appeal',
            'mailing_type': 'sms',
            'body_plaintext': 'Thank you for your support',
            'mailing_model_id': cls.env['ir.model']._get_id('res.partner'),
            'mailing_domain': [('id', 'in', cls.partners.ids)],
            'sms_force_send': True,
        })

    def test_campaign_traces_follow_flydove_status(self):
        with patch(REQUEST, return_value=FakeResponse(200, {'batch_id': 'M1'})) as mock:
            self.mailing.action_send_sms()
        sent = sorted(d['to'] for d in mock.call_args.kwargs['json']['destinations'])
        self.assertEqual(sent, ['+886912345678', '+886987654321'])
        traces = self.mailing.mailing_trace_ids
        self.assertEqual(len(traces), 2)
        self.assertEqual(set(traces.mapped('trace_status')), {'pending'})

        with patch(REQUEST, return_value=FakeResponse(200, {
                'data': [
                    {'to': '886912345678', 'code': 2002, 'description': '已送達手機'},
                    {'to': '886987654321', 'code': 4001, 'description': '無效的手機號碼'},
                ],
                'meta': {'next_page': None}})):
            self.env['sms.flydove.message']._cron_poll_delivery()
        by_number = {t.sms_number: t for t in traces}
        self.assertEqual(by_number['+886912345678'].trace_status, 'sent')
        self.assertEqual(by_number['+886987654321'].trace_status, 'bounce')
        self.assertEqual(by_number['+886987654321'].failure_type, 'sms_invalid_destination')

    def test_test_button_uses_flydove(self):
        wizard = self.env['mailing.sms.test'].create({
            'mailing_id': self.mailing.id, 'numbers': '+886 912 345 678\n12'})
        with patch(REQUEST, return_value=FakeResponse(200, {'batch_id': 'T1'})) as mock, \
                patch('odoo.addons.sms.tools.sms_api.SmsApi._send_sms_batch') as mock_iap:
            wizard.action_send_sms()
        mock_iap.assert_not_called()
        self.assertEqual(mock.call_args.kwargs['json']['destinations'], [{'to': '+886912345678'}])
        log = self.mailing.message_ids[0].body
        self.assertIn('Test SMS successfully sent to +886912345678', log)
        self.assertIn('not correctly encoded: 12', log)
