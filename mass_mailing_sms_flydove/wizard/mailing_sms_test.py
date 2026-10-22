from markupsafe import Markup

from odoo import _, models


class MailingSmsTest(models.TransientModel):
    _inherit = 'mailing.sms.test'

    def action_send_sms(self):
        # The standard wizard calls the IAP SmsApi directly instead of sms.sms._send,
        # so it would bypass Flydove; send the test through sms.sms instead.
        if self.env['sms.sms']._flydove_api() is None:
            return super().action_send_sms()
        self.ensure_one()

        numbers = [number.strip() for number in self.numbers.splitlines()]
        sanitized_numbers = [self.env.user._phone_format(number=number) for number in numbers]
        invalid_numbers = [number for sanitized, number in zip(sanitized_numbers, numbers) if not sanitized]

        record = self.env[self.mailing_id.mailing_model_real].search([], limit=1)
        body = self.mailing_id.body_plaintext
        if record:
            # Returns a proper error if there is a syntax error with qweb
            body = self.env['mail.render.mixin']._render_template(
                body, self.mailing_id.mailing_model_real, record.ids)[record.id]

        sms_sudo = self.env['sms.sms'].sudo().create(
            [{'body': body, 'number': number} for number in sanitized_numbers if number])
        sms_sudo._send(unlink_failed=False, unlink_sent=False, raise_exception=False)

        failure_labels = dict(sms_sudo._fields['failure_type']._description_selection(self.env))
        notification_messages = []
        if invalid_numbers:
            notification_messages.append(_('The following numbers are not correctly encoded: %s',
                                           ', '.join(invalid_numbers)))
        for sms in sms_sudo:
            if sms.state in ('process', 'pending', 'sent'):
                notification_messages.append(_('Test SMS successfully sent to %s', sms.number))
            else:
                notification_messages.append(_(
                    "Test SMS could not be sent to %(destination)s: %(state)s",
                    destination=sms.number,
                    state=failure_labels.get(sms.failure_type) or _("An error occurred."),
                ))
        sms_sudo.to_delete = True

        if notification_messages:
            message_body = Markup(
                f"<ul>{''.join('<li>%s</li>' for _ in notification_messages)}</ul>"
            ) % tuple(notification_messages)
            self.mailing_id._message_log(body=message_body)
        return True
