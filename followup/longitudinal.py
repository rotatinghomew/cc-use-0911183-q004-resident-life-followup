"""纵向分析：分析对象由入住与随访资格确定，区分观察变化、构成变化与不可识别部分。"""
from datetime import date, timedelta
from statistics import mean

from .eligibility import latest_attempts

__all__ = ['month_bounds', 'month_window', 'response_history', 'monthly_snapshot', 'decompose', 'sensitivity', 'longitudinal_report']

ANALYSIS_NOTE = '本报告为服务质量分析，不构成诊断或个人照护建议'

EXIT_REASON_LABELS = {'discharge': '离院', 'transfer': '转院', 'deceased': '死亡', 'unspecified': '未注明'}

MISSING_LABELS = {
    'no_consent': '未同意随访',
    'no_contact': '无可用联系方式',
    'refused': '已拒访',
    'invalid_contact': '联系方式无效待更正',
    'absent_hospital': '暂时住院',
    'absent_other': '暂时离院（非住院）',
    'awaiting_record': '已联系待登记问卷',
    'unreachable_recent': '近期未联系上',
    'cooling': '联系间隔未满',
    'not_attempted': '可联系但未尝试',
}

COMPONENT_LABELS = {
    'within_same_mode': '同一人同一回答方式的期间变化',
    'mode_switched': '回答方式切换者的前后差异（不与同方式合并）',
    'joiners': '本期新应答者带入',
    'leavers': '上期应答本期流失者带走',
    'share': '留答者占比变化的机械影响',
}

SCENARIO_LABELS = {
    'floor': '失访者全部按最低分 1 计',
    'ceiling': '失访者全部按最高分 5 计',
    'observed': '失访者按当期已答者均值计',
    'last': '失访者按本人最近一次观察计（跨回答方式仅为假设，不与本期测量拼接；无历史时依次回退到当期已答均值、全部已答均值、中性 3）',
    'most_favorable': '最有利于上升结论的组合（前期失访按 1、后期失访按 5）',
    'least_favorable': '最不利于上升结论的组合（前期失访按 5、后期失访按 1）',
}


def _r4(value):
    return None if value is None else round(value, 4)


def _validate_month(month):
    if not isinstance(month, str):
        raise ValueError('月份须为 YYYY-MM 格式')
    parts = month.split('-')
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError('月份须为 YYYY-MM 格式')
    try:
        year, mon = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError('月份须为 YYYY-MM 格式') from None
    if not 1 <= mon <= 12:
        raise ValueError('月份须为 YYYY-MM 格式')
    return year, mon


def month_bounds(month):
    year, mon = _validate_month(month)
    first = date(year, mon, 1)
    last = date(year + (mon == 12), mon % 12 + 1, 1) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def month_window(end_month, window):
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 36:
        raise ValueError('窗口须为 1 到 36 的整数')
    year, mon = _validate_month(end_month)
    months = []
    for _ in range(window):
        months.append(f'{year:04d}-{mon:02d}')
        year, mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    return sorted(months)


def response_history(store):
    """每位老人历次计分问卷（日期、分项均分、回答身份），按日期排序。"""
    history = {}
    for row in store.all('responses'):
        observed = [value for value in row['items'] if value is not None]
        if observed:
            history.setdefault(row['resident'], []).append((row['date'], mean(observed), row['respondent']))
    for entries in history.values():
        entries.sort()
    return history


def _cohort(store, first, last):
    """当月任一自然日具备在院随访资格的老人，与是否有问卷无关。"""
    members = {}
    for row in store.all('residents'):
        if row['left'] is None:
            start, end = max(row['entered'], first), last
        else:
            left_limit = (date.fromisoformat(row['left']) - timedelta(days=1)).isoformat()
            start, end = max(row['entered'], first), min(last, left_limit)
        if start <= end:
            members[row['id']] = row
    return members


def _person_months(store, first, last, members):
    """按人按月汇总：部分缺答仍计分；同人同月多种回答身份记为 mixed，不与单一身份拼接。"""
    per = {}
    for row in store.all('responses'):
        if row['resident'] not in members or not first <= row['date'] <= last:
            continue
        observed = [value for value in row['items'] if value is not None]
        if not observed:
            continue
        entry = per.setdefault((row['resident'], row['respondent']), {'items': [], 'responses': 0, 'partial': 0, 'answered': 0, 'total': 0})
        entry['items'].extend(observed)
        entry['responses'] += 1
        entry['partial'] += int(any(value is None for value in row['items']))
        entry['answered'] += len(observed)
        entry['total'] += len(row['items'])
    people = {}
    for (pid, mode), entry in per.items():
        person = people.setdefault(pid, {'items': [], 'modes': [], 'responses': 0, 'partial': 0, 'answered': 0, 'total': 0, 'by_mode': {}})
        person['items'].extend(entry['items'])
        person['modes'].append(mode)
        person['responses'] += entry['responses']
        person['partial'] += entry['partial']
        person['answered'] += entry['answered']
        person['total'] += entry['total']
        person['by_mode'][mode] = mean(entry['items'])
    result = {}
    for pid, person in people.items():
        result[pid] = {
            'score': mean(person['items']),
            'mode': person['modes'][0] if len(person['modes']) == 1 else 'mixed',
            'responses': person['responses'],
            'partial': person['partial'],
            'answered_share': person['answered'] / person['total'],
            'by_mode': person['by_mode'],
        }
    return result


def _missing_reason(resident, first, last, absences, attempts):
    if not resident['consent']:
        return 'no_consent'
    if not resident['contact']:
        return 'no_contact'
    latest, latest_any = latest_attempts(attempts)
    if latest and latest['result'] == 'refused':
        return 'refused'
    if latest_any and latest_any['result'] == 'invalid' and latest_any.get('contact') == resident['contact']:
        return 'invalid_contact'
    for absence in absences:
        if absence['start'] <= last and absence['end'] >= first:
            return 'absent_hospital' if absence.get('reason') == 'hospital' else 'absent_other'
    if latest and latest['result'] == 'responded' and first <= latest['date'] <= last:
        return 'awaiting_record'
    if latest and date.fromisoformat(last) < date.fromisoformat(latest['date']) + timedelta(days=resident['contact_gap_days']):
        return 'unreachable_recent' if latest['result'] == 'unreachable' else 'cooling'
    return 'not_attempted'


def _snapshot(store, month):
    first, last = month_bounds(month)
    members = _cohort(store, first, last)
    people = _person_months(store, first, last, members)
    absences = {}
    for row in store.all('absences'):
        if row['resident'] in members and row['start'] <= last and row['end'] >= first:
            absences.setdefault(row['resident'], []).append(row)
    attempts = {}
    for row in store.all('contacts'):
        if row['resident'] in members and row['date'] <= last:
            attempts.setdefault(row['resident'], []).append(row)
    missing = {}
    for pid, resident in members.items():
        if pid not in people:
            reason = _missing_reason(resident, first, last, absences.get(pid, []), attempts.get(pid, []))
            missing.setdefault(reason, []).append(pid)
    return {'month': month, 'first': first, 'last': last, 'members': members, 'people': people, 'missing': missing, 'absent': absences}


def monthly_snapshot(store, month):
    snap = _snapshot(store, month)
    members, people, missing = snap['members'], snap['people'], snap['missing']
    scores = [person['score'] for person in people.values()]
    by_mode = {}
    for person in people.values():
        for mode, value in person['by_mode'].items():
            by_mode.setdefault(mode, []).append(value)
    exited = [row for row in members.values() if row['left'] is not None and row['left'] <= snap['last']]
    exit_reasons = {}
    for row in exited:
        exit_reasons.setdefault(row.get('left_reason') or 'unspecified', []).append(row['id'])
    return {
        'month': month,
        'cohort': {
            'total': len(members),
            'members': sorted(members),
            'entered': sorted(row['id'] for row in members.values() if row['entered'] >= snap['first']),
            'exited': sorted(row['id'] for row in exited),
            'exit_reasons': {reason: sorted(ids) for reason, ids in sorted(exit_reasons.items())},
            'absent': sorted(snap['absent']),
        },
        'observed': {
            'people': len(people),
            'responses': sum(person['responses'] for person in people.values()),
            'mean': _r4(mean(scores)) if scores else None,
            'partial_responses': sum(person['partial'] for person in people.values()),
            'answered_share': _r4(mean([person['answered_share'] for person in people.values()])) if people else None,
            'by_mode': {mode: {'people': len(values), 'mean': _r4(mean(values))} for mode, values in sorted(by_mode.items())},
        },
        'missing': {
            'total': sum(len(ids) for ids in missing.values()),
            'reasons': {reason: sorted(ids) for reason, ids in sorted(missing.items())},
        },
        'coverage': _r4(len(people) / len(members)) if members else None,
    }


def decompose(store, month_from, month_to):
    """两期已答均值变化的精确分解：各分量之和恒等于观察变化；失访部分不可识别，另见 sensitivity。"""
    _validate_month(month_from)
    _validate_month(month_to)
    if not month_from < month_to:
        raise ValueError('比较月份须为先后两期')
    earlier, later = _snapshot(store, month_from), _snapshot(store, month_to)
    people_from, people_to = earlier['people'], later['people']
    result = {
        'from': month_from,
        'to': month_to,
        'cohort': {
            'from': len(earlier['members']),
            'to': len(later['members']),
            'missing_from': len(earlier['members']) - len(people_from),
            'missing_to': len(later['members']) - len(people_to),
        },
        'missing': {
            'from': {reason: sorted(ids) for reason, ids in sorted(earlier['missing'].items())},
            'to': {reason: sorted(ids) for reason, ids in sorted(later['missing'].items())},
        },
        'component_labels': COMPONENT_LABELS,
    }
    if not people_from or not people_to:
        result['available'] = False
        result['note'] = '至少一期无已答问卷，观察值比较不可用；人员构成与失访假设检查仍列出'
        result['sensitivity'] = sensitivity(store, month_from, month_to)
        return result
    ids_from, ids_to = set(people_from), set(people_to)
    both = ids_from & ids_to
    stayers = sorted(pid for pid in both if people_from[pid]['mode'] == people_to[pid]['mode'] and people_from[pid]['mode'] != 'mixed')
    switchers = sorted(both - set(stayers))
    joiners = sorted(ids_to - ids_from)
    leavers = sorted(ids_from - ids_to)
    n_from, n_to = len(people_from), len(people_to)
    mean_from = mean(person['score'] for person in people_from.values())
    mean_to = mean(person['score'] for person in people_to.values())
    components = {
        'within_same_mode': sum(people_to[pid]['score'] - people_from[pid]['score'] for pid in stayers) / n_to,
        'mode_switched': sum(people_to[pid]['score'] - people_from[pid]['score'] for pid in switchers) / n_to,
        'joiners': sum(people_to[pid]['score'] for pid in joiners) / n_to,
        'leavers': -sum(people_from[pid]['score'] for pid in leavers) / n_from,
        'share': sum(people_from[pid]['score'] for pid in both) * (1 / n_to - 1 / n_from),
    }
    result.update({
        'available': True,
        'observed': {
            'mean_from': _r4(mean_from),
            'mean_to': _r4(mean_to),
            'change': _r4(mean_to - mean_from),
            'people_from': n_from,
            'people_to': n_to,
        },
        'components': {name: _r4(value) for name, value in components.items()},
        'components_sum': _r4(sum(components.values())),
        'groups': {
            'stayers_same_mode': {
                'residents': stayers,
                'mean_from': _r4(mean([people_from[pid]['score'] for pid in stayers])) if stayers else None,
                'mean_to': _r4(mean([people_to[pid]['score'] for pid in stayers])) if stayers else None,
            },
            'mode_switched': {
                'residents': switchers,
                'detail': [{'resident': pid, 'from_mode': people_from[pid]['mode'], 'to_mode': people_to[pid]['mode']} for pid in switchers],
            },
            'joiners': {
                'residents': joiners,
                'mean_to': _r4(mean([people_to[pid]['score'] for pid in joiners])) if joiners else None,
            },
            'leavers': {
                'residents': leavers,
                'mean_from': _r4(mean([people_from[pid]['score'] for pid in leavers])) if leavers else None,
            },
        },
        'unidentified': f"两期分别有 {result['cohort']['missing_from']}、{result['cohort']['missing_to']} 名在院者未答；其得分与变化无法由现有资料识别，sensitivity 给出不同假设下的结论范围",
        'sensitivity': sensitivity(store, month_from, month_to),
    })
    return result


def sensitivity(store, month_from, month_to):
    """对失访者得分的假设检查：边界为任意填补下的理论范围，情景为合理假设示例，均不代表失访者真实得分。"""
    _validate_month(month_from)
    _validate_month(month_to)
    if not month_from < month_to:
        raise ValueError('比较月份须为先后两期')
    earlier, later = _snapshot(store, month_from), _snapshot(store, month_to)
    if not earlier['members'] or not later['members']:
        return {'available': False, 'note': '至少一期无在院随访对象'}
    history = response_history(store)
    all_scores = [score for entries in history.values() for _, score, _ in entries]
    overall = mean(all_scores) if all_scores else None

    def observed_mean(snap):
        return mean(person['score'] for person in snap['people'].values()) if snap['people'] else None

    def imputed_mean(snap, value_for):
        total = sum(person['score'] for person in snap['people'].values())
        for pid in snap['members']:
            if pid not in snap['people']:
                total += value_for(pid, snap)
        return total / len(snap['members'])

    def last_value(pid, snap):
        entries = [entry for entry in history.get(pid, []) if entry[0] < snap['first']]
        if entries:
            return entries[-1][1]
        current = observed_mean(snap)
        if current is not None:
            return current
        return overall if overall is not None else 3.0

    scenarios = {}
    for name, value in [('floor', 1.0), ('ceiling', 5.0)]:
        scenarios[name] = (imputed_mean(earlier, lambda pid, snap, v=value: v), imputed_mean(later, lambda pid, snap, v=value: v))
    skipped = {}
    if observed_mean(earlier) is not None and observed_mean(later) is not None:
        scenarios['observed'] = (imputed_mean(earlier, lambda pid, snap: observed_mean(snap)), imputed_mean(later, lambda pid, snap: observed_mean(snap)))
    else:
        skipped['observed'] = '至少一期无已答问卷，该情景不可用'
    scenarios['last'] = (imputed_mean(earlier, last_value), imputed_mean(later, last_value))
    scenarios['most_favorable'] = (imputed_mean(earlier, lambda pid, snap: 1.0), imputed_mean(later, lambda pid, snap: 5.0))
    scenarios['least_favorable'] = (imputed_mean(earlier, lambda pid, snap: 5.0), imputed_mean(later, lambda pid, snap: 1.0))
    out = {name: {'mean_from': _r4(pair[0]), 'mean_to': _r4(pair[1]), 'change': _r4(pair[1] - pair[0])} for name, pair in scenarios.items()}
    min_change = out['least_favorable']['change']
    max_change = out['most_favorable']['change']
    identified = min_change > 0 or max_change < 0
    if identified:
        direction_note = '任意填补假设下变化方向一致，结论对失访假设稳健，但仍不代表失访者真实改善'
    else:
        direction_note = '变化方向取决于对失访者的假设，现有资料无法判定'
    return {
        'available': True,
        'missing_from': len(earlier['members']) - len(earlier['people']),
        'missing_to': len(later['members']) - len(later['people']),
        'scenarios': out,
        'scenario_labels': SCENARIO_LABELS,
        'skipped': skipped,
        'bounds': {'min_change': min_change, 'max_change': max_change, 'sign_identified': identified},
        'note': '边界为任意填补下的理论范围；情景仅为假设示例，均不代表失访者真实得分。' + direction_note,
    }


def longitudinal_report(store, month, window=6, compare_from=None, compare_to=None):
    months = month_window(month, window)
    if compare_from is not None or compare_to is not None:
        if not compare_from or not compare_to:
            raise ValueError('需要同时提供 from 与 to 参数')
        change = decompose(store, compare_from, compare_to)
    elif len(months) > 1:
        change = decompose(store, months[-2], months[-1])
    else:
        change = None
    return {
        'note': ANALYSIS_NOTE,
        'month': month,
        'window': window,
        'missing_labels': MISSING_LABELS,
        'exit_labels': EXIT_REASON_LABELS,
        'months': [monthly_snapshot(store, item) for item in months],
        'change': change,
    }
