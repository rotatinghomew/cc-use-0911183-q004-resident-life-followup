from .eligibility import contactable


def assign_contact(store, resident, interviewer, day):
    allowed = {row['id']: row for row in contactable(store, day)}
    person = store.get('interviewers', interviewer)
    if resident not in allowed or allowed[resident]['site'] not in person['sites']:
        raise ValueError('不符合联系资格或访员服务范围')
    for job in store.all('jobs'):
        if job['resident'] == resident and job['status'] == 'open':
            raise ValueError('已有未结束的联系安排')
    key = resident + ':' + day
    value = {'id': key, 'resident': resident, 'interviewer': interviewer, 'date': day, 'status': 'open', 'reason': '日常随访'}
    store.put('jobs', value, expected=0)
    return value


def finish_contact(store, job_id, result):
    if result not in ['responded', 'unreachable', 'refused']:
        raise ValueError('联系结果不合法')
    row = store.get('jobs', job_id)
    if row['status'] != 'open':
        raise ValueError('联系安排已结束')
    value = {'id': job_id, 'resident': row['resident'], 'date': row['date'], 'result': result}
    with store.transaction():
        store.connection.execute('INSERT INTO records VALUES(?,?,?,1)', ('contacts', job_id, __import__('json').dumps(value)))
        row['status'] = result
        store.connection.execute('UPDATE records SET payload=?,revision=revision+1 WHERE kind=? AND key=?', (__import__('json').dumps(row), 'jobs', job_id))
    return row
