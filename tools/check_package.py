"""Offline checks only. Does not import app/bridge/shop or access any chain."""
import ast
import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]


def main():
    syntax = []
    for folder in [ROOT, ROOT / 'tools']:
        for path in sorted(folder.glob('*.py')):
            ast.parse(path.read_bytes(), filename=str(path))
            syntax.append(path.relative_to(ROOT).as_posix())

    source = json.loads((ROOT / 'docs/source-export-manifest.json').read_text(encoding='utf-8'))
    for entry in source['files']:
        path = ROOT / entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['path']
    screenshots = json.loads((ROOT / 'docs/screenshot-manifest.json').read_text(encoding='utf-8'))
    for entry in screenshots['files']:
        assert hashlib.sha256((ROOT / entry['path']).read_bytes()).hexdigest() == entry['sha256'], entry['path']

    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html']))
    env.filters['person'] = lambda address: {'ALICE': 'Alice · 学生A', 'BOB': 'Bob · 学生B', 'ADMIN': '校园管理员'}.get(address, '其他链上账户')
    templates = sorted(path.name for path in (ROOT / 'templates').glob('*.html'))
    for name in templates:
        env.get_template(name)

    categories = {'tech': '技术成长', 'service': '志愿服务', 'green': '绿色校园'}
    tasks = {f'T{i}': dict(ID=f'T{i}', Title=f'MOCK ONLY 任务{i}', Category=cat, Reward=40+i) for i, cat in enumerate(['tech', 'service', 'green', 'tech'])}
    claims = [dict(ID=f'C{i}', TaskID=f'T{i}', Owner='ALICE', Status=status, Proof='a'*64, Reason='MOCK ONLY', BadgeID='B0' if status=='APPROVED' else '', ReviewTx='b'*64) for i, status in enumerate(['CLAIMED', 'SUBMITTED', 'APPROVED', 'REJECTED'])]
    badges = [dict(ID='B0', Title='MOCK ONLY 徽章', Owner='ALICE', Category='green', Proof='c'*64, ClaimID='C2', Tx='d'*64)]
    base = dict(
        session={}, request=SimpleNamespace(path='/'), appearance={},
        labels={'admin': '校园管理员', 'alice': 'Alice · 学生A', 'bob': 'Bob · 学生B'},
        users=['admin', 'alice', 'bob'], csrf='MOCK_CSRF', categories=categories,
        statuses={'CLAIMED': '已领取', 'SUBMITTED': '待审核', 'APPROVED': '已完成', 'REJECTED': '待补充材料'},
        accounts={'admin': 'ADMIN', 'alice': 'ALICE', 'bob': 'BOB'}, user=None, error='', rid='MOCK_RID',
        state={'ft': {'Supply': 999, 'Balances': {'ALICE': 99}}, 'task': {'Tasks': tasks, 'Claims': {c['ID']: c for c in claims}, 'Done': {}}, 'nft': {'Badges': {'B0': badges[0]}}},
        claims=claims, badges=badges, completed={'green'}, pending=1, balance=99, last=None,
    )
    cases = []
    for user in [None, 'admin', 'alice', 'bob']:
        ctx = copy.deepcopy(base)
        ctx.update(user=user, session={'user': user} if user else {})
        if user == 'bob':
            ctx.update(claims=[], badges=[], completed=set(), pending=0, balance=0)
        cases.append(('index.html', f'index-{user}', ctx))
    for user in ['alice', 'admin']:
        ctx = copy.deepcopy(base)
        ctx.update(user=user, session={'user': user}, claims=[], badges=[], completed=set(), pending=0, balance=0)
        ctx['state']['task'].update(Tasks={}, Claims={})
        ctx['state']['nft']['Badges'] = {}
        cases.append(('index.html', f'empty-{user}', ctx))
        ctx = copy.deepcopy(base)
        ctx.update(user=user, session={'user': user}, last={'ok': True, 'tx_id': 'e'*64, 'height': 5, 'data': 'MOCK ONLY'})
        cases.append(('index.html', f'receipt-{user}', ctx))
    for user in [None, 'alice']:
        ctx = {k: base[k] for k in ['request', 'appearance', 'labels', 'users', 'csrf', 'categories', 'statuses', 'accounts']}
        ctx.update(user=user, session={'user': user} if user else {}, error='MOCK_INTERNAL_PATH')
        cases.append(('index.html', f'error-{user}', ctx))
    goods = {'orbit': dict(name='星环', slot='avatar', description='MOCK ONLY', price=20), 'aurora': dict(name='极光', slot='background', description='MOCK ONLY', price=35)}
    for user, status in [('alice', 'paid'), ('alice', 'pending'), ('alice', 'failed'), ('admin', 'paid')]:
        ctx = copy.deepcopy(base)
        ctx.update(user=user, session={'user': user}, request=SimpleNamespace(path='/shop'), goods=goods, own={sku: {'status': status} for sku in goods}, records=[dict(sku='orbit', price=20, user=user, created='MOCK ONLY', id='MOCK_ORDER', tx='', status=status, error='')], message='')
        cases.append(('shop.html', f'shop-{user}-{status}', ctx))
    for user in [None, 'alice', 'admin']:
        ctx = copy.deepcopy(base)
        ctx.pop('user')
        ctx.update(session={'user': user} if user else {}, request=SimpleNamespace(path='/verify'), badge=badges[0], match=None, token_id='B0')
        cases.append(('verify.html', f'verify-{user}', ctx))

    rendered = {}
    for template, name, ctx in cases:
        html = env.get_template(template).render(**ctx)
        assert '<html' in html and '</html>' in html, name
        if name.startswith('error-'):
            assert 'MOCK_INTERNAL_PATH' not in html, name
        if template == 'index.html' and ctx.get('user') and not ctx.get('error'):
            assert 'id="v10-dashboard"' in html
            assert html.count('class="side-link"') == (7 if ctx['user']=='admin' else 6), name
        rendered[name] = html

    node = shutil.which('node')
    javascript = 'NOT RUN: node not installed'
    if node:
        for script in re.findall(r'<script>(.*?)</script>', rendered['index-alice'], re.S):
            check = subprocess.run([node, '--check'], input=script, text=True, encoding='utf-8', capture_output=True)
            assert check.returncode == 0, check.stderr
        javascript = 'PASS'

    report = {
        'python_syntax': {'status': 'PASS', 'files': syntax},
        'source_byte_integrity': {'status': 'PASS', 'count': len(source['files'])},
        'screenshot_byte_integrity': {'status': 'PASS', 'count': len(screenshots['files'])},
        'jinja_compilation': {'status': 'PASS', 'templates': templates},
        'template_cases': {'status': 'MOCK ONLY', 'passed': len(cases), 'cases': list(rendered)},
        'javascript_syntax': javascript,
        'live_chain_tests': 'NOT RUN',
        'go_build': 'NOT RUN',
        'fresh_dependency_install': 'NOT RUN',
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
