# odoo-sms-flydove

Odoo 18 modules that send Odoo SMS through [Flydove / 飛信資訊](https://www.flydove.net)
(SmartDove transactional SMS API) instead of Odoo IAP.

| Module | Purpose |
|---|---|
| `sms_flydove` | Provider switch in *Settings → General Settings → SMS Provider* (Odoo IAP / Flydove). Routes `sms.sms` sending to Flydove and polls delivery reports every 5 minutes (Flydove has no delivery webhook), updating chatter notifications and SMS marketing traces. |
| `mass_mailing_sms_flydove` | Auto-installed bridge with SMS Marketing: the mailing *Test* button also goes through Flydove. |

## Configuration

1. Get an *Admin API Token* at <https://console2.flydove.net/apis> (SmartDove SMS must be enabled on your account).
2. *Settings → General Settings → SMS Provider*: choose **Flydove**, paste the token, save.

Numbers are sent in E.164 format; Taiwanese local mobiles (`0912-345-678`) are converted to `+886912345678`.
Delivery status codes 2002 → delivered; 4001/4003 → invalid destination (bounce); 4030 → not allowed;
4080 → expired; others see `sms_flydove/tools/flydove_api.py`.

API reference: <https://documenter.getpostman.com/view/32479177/2sA3XY7JPs>

## License

LGPL-3
