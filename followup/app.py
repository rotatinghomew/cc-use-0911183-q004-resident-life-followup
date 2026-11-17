from pathlib import Path
import json

from .eligibility import *
from .questionnaires import *
from .visits import *


class Application:
    def __init__(self, store):
        self.store = store

    def seed(self):
        directory = Path(__file__).resolve().parent.parent / 'fixtures'
        for path in sorted(directory.glob('*.json')):
            if not self.store.all(path.stem):
                self.store.put_many(path.stem, json.loads(path.read_text(encoding='utf-8')))

    def demo(self):
        return {'eligible': [row['id'] for row in eligible(self.store, '2026-11-01')], 'observed': monthly_observed(self.store, '2026-10'), 'contactable': [row['id'] for row in contactable(self.store, '2026-11-01')]}

    def check(self):
        value = self.demo()
        return {'status': 'ok', 'summary': value}

    def call(self, method, route, payload):
        if method == 'GET' and route == 'summary':
            return self.demo()
        if method == 'POST' and route == 'response':
            return {'revision': save_response(self.store, payload)}
        if method == 'POST' and route == 'assign':
            return assign_contact(self.store, payload['resident'], payload['interviewer'], payload['date'])
        if method == 'POST' and route == 'contact-result':
            return finish_contact(self.store, payload['job'], payload['result'])
        raise KeyError('接口不存在')
