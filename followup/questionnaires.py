from statistics import mean


def save_response(store, row):
    store.get('residents', row['resident'])
    if row['respondent'] not in ['self', 'family', 'assisted']:
        raise ValueError('回答身份不合法')
    if any(value is not None and not 1 <= value <= 5 for value in row['items']):
        raise ValueError('问卷分项超出范围')
    return store.put('responses', row)


def monthly_observed(store, month):
    values = []
    people = set()
    for row in store.all('responses'):
        if row['date'].startswith(month):
            observed = [value for value in row['items'] if value is not None]
            if observed:
                values.append(mean(observed))
                people.add(row['resident'])
    return {'month': month, 'responses': len(values), 'people': len(people), 'observed_mean': mean(values) if values else None}
