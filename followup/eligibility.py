from datetime import date, timedelta


def eligible(store, day):
    date.fromisoformat(day)
    return [row for row in store.all('residents') if row['entered'] <= day and (row['left'] is None or day < row['left'])]


def contactable(store, day):
    current = date.fromisoformat(day)
    result = []
    for resident in eligible(store, day):
        if not resident['consent'] or not resident['contact']:
            continue
        attempts = [row for row in store.all('contacts') if row['resident'] == resident['id'] and row['date'] <= day]
        latest = max(attempts, key=lambda row: row['date']) if attempts else None
        if latest and (latest['result'] == 'refused' or current < date.fromisoformat(latest['date']) + timedelta(days=resident['contact_gap_days'])):
            continue
        result.append(resident)
    return result
