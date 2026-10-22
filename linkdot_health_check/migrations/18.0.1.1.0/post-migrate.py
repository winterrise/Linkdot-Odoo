# 把舊紀錄選過的聯絡人轉成醫療機構，並接回 provider_id。
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not column_exists(cr, 'linkdot_health_check', 'legacy_provider_partner_id'):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    Provider = env['linkdot.health.check.provider'].with_context(active_test=False)
    cr.execute("""
        SELECT DISTINCT c.legacy_provider_partner_id, c.check_type = 'special'
          FROM linkdot_health_check c
         WHERE c.legacy_provider_partner_id IS NOT NULL
    """)
    rows = cr.fetchall()
    partners = env['res.partner'].browse({pid for pid, _special in rows}).exists()
    special_partners = {pid for pid, special in rows if special}
    for partner in partners:
        provider = Provider.search([('name', '=', partner.name), ('company_id', '=', False)], limit=1)
        if not provider:
            provider = Provider.create({
                'name': partner.name,
                'phone': partner.phone or partner.mobile,
                'address': ' '.join(partner._display_address(without_company=True).split()),
                'company_id': False,
                'offers_special': partner.id in special_partners,
            })
        elif partner.id in special_partners and not provider.offers_special:
            provider.offers_special = True
        cr.execute(
            "UPDATE linkdot_health_check SET provider_id = %s WHERE legacy_provider_partner_id = %s",
            (provider.id, partner.id))
    cr.execute("ALTER TABLE linkdot_health_check DROP COLUMN legacy_provider_partner_id")
    _logger.info("linkdot_health_check: converted %d partner(s) into medical institutions", len(partners))
