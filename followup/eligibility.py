from datetime import date, timedelta

__all__ = ['eligible', 'contactable', 'latest_attempts']


def eligible(store, day):
    date.fromisoformat(day)
    return [row for row in store.all('residents') if row['entered'] <= day and (row['left'] is None or day < row['left'])]


def latest_attempts(attempts):
    """最近联系中，无效联系方式的记录不产生间隔，也不覆盖此前的拒访。"""
    relevant = [row for row in attempts if row['result'] != 'invalid']
    latest_any = max(attempts, key=lambda row: (row['date'], row['id'])) if attempts else None
    latest = max(relevant, key=lambda row: (row['date'], row['id'])) if relevant else None
    return latest, latest_any


def contactable(store, day):
    current = date.fromisoformat(day)
    result = []
    for resident in eligible(store, day):
        if not resident['consent'] or not resident['contact']:
            continue
        attempts = [row for row in store.all('contacts') if row['resident'] == resident['id'] and row['date'] <= day]
        latest, latest_any = latest_attempts(attempts)
        if latest and latest['result'] == 'refused':
            continue
        if latest_any and latest_any['result'] == 'invalid' and latest_any.get('contact') == resident['contact']:
            continue
        if latest and current < date.fromisoformat(latest['date']) + timedelta(days=resident['contact_gap_days']):
            continue
        result.append(resident)
    return result
