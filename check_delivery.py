"""Independent, read-only delivery watchdog. No API calls and never sends mail."""
import argparse
import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from run_status import write_private_json

ET = ZoneInfo('America/New_York')


def read_object(path):
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object')
    return value


def check_delivery(root, now=None, state=None):
    now = (now or datetime.now(ET)).astimezone(ET)
    today = now.date().isoformat()
    report = {'checked_at': now.isoformat(), 'edition_date': today, 'alert': False}
    if now.weekday() >= 5 or now.time() < time(6, 45):
        return dict(report, outcome='not_due')
    state = state or root / 'state'
    try:
        run = read_object(state / 'production-run.json')
        if datetime.fromisoformat(run['started_at']).astimezone(ET).date() == now.date():
            report['run'] = run
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError):
        report['run_record_error'] = True
    accepted, uncertain, errors = [], [], []
    # Include previews generated before today but delivered today; ignore personal tests.
    for marker in sorted((root / 'previews').glob('*/group-send-attempt.json')):
        try:
            attempt = read_object(marker)
            stamp = datetime.fromisoformat(attempt['at'])
            if stamp.tzinfo is None:
                raise ValueError('Naive delivery time')
            if stamp.astimezone(ET).date() != now.date():
                continue
            if attempt.get('group') is not True:
                raise ValueError('Invalid group marker')
            payload = read_object(marker.parent / 'delivery.json')
            if payload.get('replay_only') or payload.get('edition_date') != today:
                errors.append(str(marker.parent))
                continue
            if attempt['status'] != 'smtp_accepted':
                uncertain.append(str(marker.parent))
                continue
            review = read_object(marker.parent / 'final-review.json')
            kind = 'service_notice' if payload.get('service_notice') else payload.get('delivery_kind', 'full')
            if kind not in ('full', 'shortened', 'service_notice'):
                raise ValueError('Unknown delivery kind')
            if kind != 'service_notice' and review.get('approved') is not True:
                raise ValueError('Accepted edition has no approval')
            accepted.append({'preview': str(marker.parent), 'kind': kind, 'at': attempt['at']})
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(str(marker.parent))
    report.update(deliveries=accepted, uncertain_attempts=uncertain, record_errors=errors)
    if uncertain or errors or len(accepted) > 1:
        return dict(report, outcome='delivery_needs_investigation', alert=True)
    if not accepted:
        return dict(report, outcome='missing_delivery', alert=True)
    kind = accepted[0]['kind']
    return dict(report, outcome=kind, alert=kind == 'service_notice')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--write-state', action='store_true')
    args = parser.parse_args()
    report = check_delivery(args.root, state=args.state_dir)
    if args.write_state:
        write_private_json((args.state_dir or args.root / 'state') / 'watchdog-status.json', report)
    print(json.dumps(report, indent=2))
    return 1 if report['alert'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
