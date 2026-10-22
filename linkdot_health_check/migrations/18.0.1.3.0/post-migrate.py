# 18.0.1.3.0：拿掉公司設定的「健康管理負責人」，提醒改發給有「健康管理人員」權限的人。
# 原本被指定為負責人的人自動補上該權限，升級後照常收到提醒。
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not column_exists(cr, 'res_company', 'health_check_officer_id'):
        return
    cr.execute("SELECT DISTINCT health_check_officer_id FROM res_company WHERE health_check_officer_id IS NOT NULL")
    user_ids = [row[0] for row in cr.fetchall()]
    env = api.Environment(cr, SUPERUSER_ID, {})
    officer_group = env.ref('linkdot_health_check.group_health_check_officer')
    users = env['res.users'].browse(user_ids).exists().filtered(
        lambda u: not u.has_group('linkdot_health_check.group_health_check_officer'))
    if users:
        users.write({'groups_id': [(4, officer_group.id)]})
        _logger.info("linkdot_health_check: granted Health Check Officer to former company officers %s", users.mapped('login'))
    cr.execute("ALTER TABLE res_company DROP COLUMN health_check_officer_id")
