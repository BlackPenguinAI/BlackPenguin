"""Production-safe P3-B smoke test: no DB, network, provider or lead writes."""
from datetime import datetime, timedelta, timezone

from app.modules.sales_agent.visit_day_funnel import (
    VERSION, choose, day_labels, message, spread_slots,
)


def main():
    now = datetime.now(timezone.utc)
    days = [(now + timedelta(days=i)).date().isoformat() for i in (1, 3, 4)]
    offer = {'version':VERSION, 'days':day_labels(days),
             'property_type_id':'smoke-cleveland','unit_id':None,
             'timezone':'UTC','expires_at':(now+timedelta(minutes=30)).isoformat()}
    for utterance in ('2', 'Second option', 'the second one', offer['days'][1]['label']):
        assert choose(utterance,offer,'smoke-cleveland',now=now) == days[1],utterance
    assert choose('2',offer,'smoke-madison',now=now) is None
    assert choose('Second option and book now',offer,'smoke-cleveland',now=now) is None
    assert choose('2',{**offer,'expires_at':(now-timedelta(seconds=1)).isoformat()},
                  'smoke-cleveland',now=now) is None
    assert [v['start_at'] for v in spread_slots([{'start_at':i} for i in range(15)])] == [0,7,14]
    assert 'Cleveland' in message('Cleveland',offer['days'],'America/Denver')
    print('P3-B production smoke: PASS (day binding, expiry, scope, spread, labeling)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
