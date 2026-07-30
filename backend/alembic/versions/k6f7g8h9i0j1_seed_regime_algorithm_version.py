"""seed regime algorithm version + config (Campaign 6, INERT)

Revision ID: k6f7g8h9i0j1
Revises: j5e6f7g8h9i0
Create Date: 2026-07-29

Prod-lands the ``regime`` v1.0.0 algorithm row + its router/specialist config,
mirroring the vendored ``vendor/regime_v1.0.0/sql/001_seed_regime_algorithm.sql``
(the R&D delivery). Ships INERT (is_active=FALSE, compute_enabled=FALSE): the
shadow-compute job writes only pl_regime_shadow, never pl_indicator_daily.

Per migrations-prod-via-main-only, the version row reaches prod THIS way (a
migration merged to main → CI/CD), never a bastion psql. Idempotent: NOT EXISTS
guards on both the version and each config param.
"""

from alembic import op

revision = "k6f7g8h9i0j1"
down_revision = "j5e6f7g8h9i0"
branch_labels = None
depends_on = None


_SEED_VERSION = """
INSERT INTO pl_algorithm_version (id, name, version, horizon, is_active, compute_enabled, description)
SELECT gen_random_uuid(),
       'regime', '1.0.0', 'short_term',
       FALSE, FALSE,
       'Two-layer regime-router + condition-specialist algo. Layer 1: causal regime detector (trailing trend/vol/RSI). Layer 2: 6 specialists (bull/bear/transition/highvol/oversold/overbought), each trained on all-history of its condition, predicting J+1 direction. SHIPPED INERT for shadow validation — forward edge unproven (in-sample fit strong, leakage-safe ~coin-flip); shadow settles it on live data.'
WHERE NOT EXISTS (
    SELECT 1 FROM pl_algorithm_version WHERE name = 'regime' AND version = '1.0.0'
);
"""

_SEED_CONFIG = """
INSERT INTO pl_algorithm_config (id, algorithm_version_id, parameter_name, value, description)
SELECT gen_random_uuid(), v.id, kv.k, kv.v, kv.d
FROM pl_algorithm_version v,
     (VALUES
        ('router_trend_band_k',        '0.8',  'trend band = k * trailing-vol; |trend20| beyond band = trending'),
        ('router_trend_window',        '20',   'trailing-return window for trend20 (trading days)'),
        ('router_trend_confirm_window','60',   'trailing-return window for trend60 (bull confirmation)'),
        ('router_vol_window',          '20',   'trailing realized-vol window (trading days)'),
        ('router_rsi_oversold',        '35',   'RSI-14 below this routes to the Oversold specialist'),
        ('router_rsi_overbought',      '65',   'RSI-14 above this routes to the Overbought specialist'),
        ('router_atr_high_value',      '48.6633','ATR-14 above this routes to the High-volatility specialist (67th pctile @ freeze)'),
        ('router_priority',            'oversold,overbought,highvol,bull,bear,transition', 'routing priority: most-specific first; each day resolves to exactly one specialist'),
        ('specialist_bull',        'regime=bull',        'trained on all confirmed-uptrend days'),
        ('specialist_bear',        'regime=bear',        'trained on all confirmed-downtrend days'),
        ('specialist_transition',  'regime=transition',  'trained on all ranging / no-trend days'),
        ('specialist_highvol',     'atr_14d>threshold',  'trained on all top-tertile-ATR days'),
        ('specialist_oversold',    'rsi_14d<35',         'trained on all oversold days'),
        ('specialist_overbought',  'rsi_14d>65',         'trained on all overbought days'),
        ('decision_horizon',       'J+1',                'specialists predict next-trading-day direction'),
        ('decision_mode',          'binary',             'OPEN if P(up)>=0.5 else HEDGE; MONITOR only as fail-safe when routed specialist is absent')
     ) AS kv(k, v, d)
WHERE v.name = 'regime' AND v.version = '1.0.0'
  AND NOT EXISTS (
    SELECT 1 FROM pl_algorithm_config c WHERE c.algorithm_version_id = v.id AND c.parameter_name = kv.k
  );
"""


def upgrade() -> None:
    op.execute(_SEED_VERSION)
    op.execute(_SEED_CONFIG)


def downgrade() -> None:
    # Remove config first (FK), then the version. Scoped to regime/1.0.0 only.
    op.execute(
        "DELETE FROM pl_algorithm_config c USING pl_algorithm_version v "
        "WHERE c.algorithm_version_id = v.id AND v.name = 'regime' AND v.version = '1.0.0'"
    )
    op.execute(
        "DELETE FROM pl_algorithm_version WHERE name = 'regime' AND version = '1.0.0'"
    )
