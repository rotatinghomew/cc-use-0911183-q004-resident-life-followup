from pathlib import Path
import json

from .eligibility import *
from .questionnaires import *
from .visits import *
from .longitudinal import *
from .planning import *


class Application:
    def __init__(self, store):
        self.store = store

    def seed(self):
        directory = Path(__file__).resolve().parent.parent / 'fixtures'
        for path in sorted(directory.glob('*.json')):
            if not self.store.all(path.stem):
                self.store.put_many(path.stem, json.loads(path.read_text(encoding='utf-8')))

    def demo(self):
        return {'eligible': [row['id'] for row in eligible(self.store, '2026-11-01')], 'observed': monthly_observed(self.store, '2026-10'), 'contactable': [row['id'] for row in contactable(self.store, '2026-11-01')], 'longitudinal': longitudinal_report(self.store, '2026-11', 3)}

    def check(self):
        value = self.demo()
        return {'status': 'ok', 'summary': value}

    def call(self, method, route, payload):
        if method == 'GET' and route == 'summary':
            return self.demo()
        if method == 'GET' and route == 'longitudinal':
            month = payload.get('month')
            if not month:
                raise ValueError('需要 month 参数（YYYY-MM）')
            try:
                window = int(payload.get('window', 6))
            except (TypeError, ValueError):
                raise ValueError('window 须为整数') from None
            return longitudinal_report(self.store, month, window, payload.get('from'), payload.get('to'))
        if method == 'GET' and route == 'plans':
            return list_plans(self.store)
        if method == 'POST' and route == 'response':
            return {'revision': save_response(self.store, payload)}
        if method == 'POST' and route == 'assign':
            return assign_contact(self.store, payload['resident'], payload['interviewer'], payload['date'])
        if method == 'POST' and route == 'plan':
            return plan_followups(self.store, payload.get('date'), payload.get('slots'), payload.get('site'))
        if method == 'POST' and route == 'contact-result':
            return finish_contact(self.store, payload['job'], payload['result'])
        raise KeyError('接口不存在')
