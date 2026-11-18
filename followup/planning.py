"""补访名单：名额优先弥补影响当前比较判断的缺口；名单理由生成时固定，事后不改写。"""
import json
from collections import Counter
from datetime import date
from statistics import mean

from .eligibility import contactable, latest_attempts
from .longitudinal import month_bounds, response_history
from .store import Conflict

__all__ = ['plan_followups', 'list_plans']

PLAN_NOTE = '名单理由在生成时固定；后续联系结果写入新记录，不改写本名单'


def _months_between(earlier, later):
    return (int(later[:4]) - int(earlier[:4])) * 12 + (int(later[5:7]) - int(earlier[5:7]))


def plan_followups(store, day, slots, site=None):
    try:
        date.fromisoformat(day)
    except TypeError:
        raise ValueError('日期须为 YYYY-MM-DD 格式') from None
    if isinstance(slots, bool) or not isinstance(slots, int) or slots < 1:
        raise ValueError('名额须为正整数')
    sites = {row['site'] for row in store.all('residents')}
    if site is not None and site not in sites:
        raise ValueError('院区不存在')
    month = day[:7]
    first, last = month_bounds(month)
    open_jobs = {job['resident'] for job in store.all('jobs') if job['status'] == 'open'}
    responded, current_modes, month_scores = set(), set(), []
    for row in store.all('responses'):
        if first <= row['date'] <= last:
            observed = [value for value in row['items'] if value is not None]
            if observed:
                responded.add(row['resident'])
                current_modes.add(row['respondent'])
                month_scores.append(mean(observed))
    current_mean = mean(month_scores) if month_scores else None
    absent_today = {row['resident'] for row in store.all('absences') if row['start'] <= day <= row['end']}
    history = response_history(store)
    attempts = {}
    for row in store.all('contacts'):
        if row['date'] <= day:
            attempts.setdefault(row['resident'], []).append(row)
    interviewers = store.all('interviewers')
    candidates, skipped = [], []
    excluded = {'open_job': 0, 'already_responded': 0}
    for resident in contactable(store, day):
        pid = resident['id']
        if site is not None and resident['site'] != site:
            continue
        if pid in open_jobs:
            excluded['open_job'] += 1
            continue
        if pid in responded:
            excluded['already_responded'] += 1
            continue
        if pid in absent_today:
            skipped.append({'resident': pid, 'site': resident['site'], 'reasons': ['当日处于暂时离院（如住院），待返回后再安排']})
            continue
        score, reasons = 0, []
        entries = history.get(pid, [])
        if not entries:
            score += 10
            reasons.append('入住以来尚无问卷，缺少纵向基线')
            months_since = _months_between(resident['entered'][:7], month)
        else:
            last_date, last_score, last_mode = entries[-1]
            months_since = _months_between(last_date[:7], month)
            if months_since >= 2:
                score += 4 + min(months_since, 8)
                reasons.append(f'已连续 {months_since} 个月无问卷，缺口影响本期与历史比较')
            elif months_since == 1:
                score += 2
                reasons.append('上月无问卷，本期尚未观察到')
            if last_mode not in current_modes:
                score += 3
                reasons.append(f'既往回答方式（{last_mode}）在本期已答者中尚无代表')
            if current_mean is not None and abs(last_score - current_mean) >= 1:
                score += 2
                reasons.append(f'上次得分 {last_score:.1f} 与本期已答均值 {current_mean:.1f} 差距较大，缺失会左右比较结论')
        latest, _ = latest_attempts(attempts.get(pid, []))
        if latest and latest['result'] == 'unreachable':
            score += 2
            reasons.append('上次联系未接通且间隔已满，重试可判断是否恢复随访')
        feasible = [row['id'] for row in interviewers if resident['site'] in row['sites']]
        if not feasible:
            skipped.append({'resident': pid, 'site': resident['site'], 'value_score': score, 'reasons': reasons + ['无访员覆盖该院区，暂不可执行']})
            continue
        candidates.append({
            'resident': pid,
            'site': resident['site'],
            'contact': resident['contact'],
            'value_score': score,
            'reasons': reasons,
            'months_since': months_since,
            'feasibility': {'consent': True, 'contact_available': True, 'interval_ok': True, 'open_job': False, 'interviewers': feasible},
        })
    candidates.sort(key=lambda item: (-item['value_score'], -item['months_since'], item['resident']))
    chosen = candidates[:slots]
    loads = Counter()
    entries, jobs = [], []
    seq = 1 + sum(1 for plan in store.all('plans') if plan['date'] == day)
    plan_id = f'plan:{day}:{seq}'
    for candidate in chosen:
        interviewer = min(candidate['feasibility']['interviewers'], key=lambda iid: (loads[iid], iid))
        loads[interviewer] += 1
        entries.append({
            'resident': candidate['resident'],
            'site': candidate['site'],
            'interviewer': interviewer,
            'value_score': candidate['value_score'],
            'reasons': candidate['reasons'],
            'feasibility': candidate['feasibility'],
        })
        jobs.append({
            'id': f"{candidate['resident']}:{day}",
            'resident': candidate['resident'],
            'interviewer': interviewer,
            'date': day,
            'status': 'open',
            'reason': '；'.join(candidate['reasons']),
            'contact': candidate['contact'],
            'plan': plan_id,
        })
    plan = {
        'id': plan_id,
        'date': day,
        'site': site,
        'slots': slots,
        'entries': entries,
        'skipped': skipped,
        'excluded': excluded,
        'unfilled': slots - len(entries),
        'note': PLAN_NOTE,
    }
    with store.transaction():
        for job in jobs:
            if store.revision('jobs', job['id']):
                raise Conflict('已存在同日的联系安排')
            store.connection.execute('INSERT INTO records VALUES(?,?,?,1)', ('jobs', job['id'], json.dumps(job, ensure_ascii=False, allow_nan=False, sort_keys=True)))
        if store.revision('plans', plan_id):
            raise Conflict('名单编号冲突')
        store.connection.execute('INSERT INTO records VALUES(?,?,?,1)', ('plans', plan_id, json.dumps(plan, ensure_ascii=False, allow_nan=False, sort_keys=True)))
    return plan


def list_plans(store):
    return {'plans': store.all('plans'), 'note': PLAN_NOTE}
