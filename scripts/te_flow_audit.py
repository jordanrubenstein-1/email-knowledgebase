"""Audit live TE Klaviyo flows, fetch step timing/subjects, and print structured data."""
import requests, os, json
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('KLAVIYO_API_KEY_TE')
headers = {'Authorization': f'Klaviyo-API-Key {API_KEY}', 'revision': '2024-10-15'}


def paginate(url):
    items = []
    while url:
        r = requests.get(url, headers=headers).json()
        items.extend(r['data'])
        url = r.get('links', {}).get('next')
    return items


def get_flow_timing(flow_id):
    """Returns dict of {action_id: cumulative_days} tracing the main path."""
    actions = paginate(f'https://a.klaviyo.com/api/flows/{flow_id}/flow-actions/?page[size]=50')
    actions.sort(key=lambda a: a['attributes'].get('order', 0))

    cumulative_seconds = 0
    action_times = {}

    for action in actions:
        attrs = action['attributes']
        atype = attrs.get('action_type', '').upper()
        if atype == 'TIME_DELAY':
            delay_s = attrs.get('settings', {}).get('delay_seconds', 0) or 0
            cumulative_seconds += delay_s
        elif atype == 'SEND_EMAIL':
            action_times[action['id']] = cumulative_seconds / 86400
    return action_times


def timing_label(days):
    if days == 0:
        return 'Immediately'
    if days < 1:
        hours = round(days * 24)
        return f'~{hours} hr'
    return f'Day {round(days)}'


# Step 1: Audit live flows
all_flows = paginate('https://a.klaviyo.com/api/flows/?page[size]=50')
print(f"Total flows: {len(all_flows)}")
live_flows = [f for f in all_flows if f['attributes']['status'] == 'live']
print(f"Live flows: {len(live_flows)}")
print()

flow_data = []
for flow in live_flows:
    fid = flow['id']
    fname = flow['attributes']['name']
    trigger = flow['attributes'].get('trigger_type', '')

    actions = paginate(f'https://a.klaviyo.com/api/flows/{fid}/flow-actions/?page[size]=50')
    live_email_actions = [
        a for a in actions
        if a['attributes']['status'] == 'live'
        and a['attributes'].get('action_type', '').upper() == 'SEND_EMAIL'
    ]
    if not live_email_actions:
        print(f"  SKIP (no live email steps): [{fid}] {fname}")
        continue

    # Get timing
    action_times = get_flow_timing(fid)

    steps = []
    for action in sorted(live_email_actions, key=lambda a: a['attributes'].get('order', 0)):
        aid = action['id']
        seq = action['attributes'].get('order', 0)
        days = action_times.get(aid, 0)

        # Get message content
        r2 = requests.get(
            f'https://a.klaviyo.com/api/flow-actions/{aid}/flow-messages/?page[size]=50',
            headers=headers
        ).json()
        for msg in r2.get('data', []):
            content = msg['attributes'].get('content', {})
            steps.append({
                'action_id': aid,
                'msg_id': msg['id'],
                'seq': seq,
                'timing_label': timing_label(days),
                'days': days,
                'subject': content.get('subject', ''),
                'preheader': content.get('preview_text', ''),
            })

    print(f"  FLOW [{fid}] {fname}  trigger={trigger}  ({len(steps)} live email steps)")
    for s in steps:
        print(f"    [{s['timing_label']}] seq={s['seq']} msg={s['msg_id']}  SL: {s['subject'][:60]}")

    flow_data.append({'id': fid, 'name': fname, 'trigger': trigger, 'steps': steps})

print()
print("=== JSON OUTPUT ===")
print(json.dumps(flow_data, indent=2))
