# 18.0.1.1.0：醫療機構由 res.partner 改為管理者預先設定的 linkdot.health.check.provider。
# 先把舊的 partner 欄位改名保留，等新模型建好後在 post-migrate 轉換。
from odoo.tools.sql import column_exists, rename_column, table_exists


def migrate(cr, version):
    if not version or table_exists(cr, 'linkdot_health_check_provider'):
        return
    if column_exists(cr, 'linkdot_health_check', 'provider_id'):
        cr.execute("ALTER TABLE linkdot_health_check DROP CONSTRAINT IF EXISTS linkdot_health_check_provider_id_fkey")
        rename_column(cr, 'linkdot_health_check', 'provider_id', 'legacy_provider_partner_id')
