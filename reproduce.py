import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--root', required=True)
parser.add_argument('--versions', nargs='+', required=True)
args = parser.parse_args()
root = Path(args.root).resolve()
evidence = root / 'evidence' / 'turbo'
evidence.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, TURBO_TELEMETRY_DISABLED='1', DO_NOT_TRACK='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null', GIT_CONFIG_NOSYSTEM='1')
for key in ['GIT_CONFIG_COUNT', 'GIT_DIR', 'GIT_WORK_TREE', 'NODE_OPTIONS', 'TURBO_SCM_BASE', 'TURBO_SCM_HEAD']:
    env.pop(key, None)
serial = 0

def run(cmd, cwd, label, extra=None):
    global serial
    serial += 1
    base = evidence / f'{serial:04d}-{label}'
    callenv = dict(env)
    if extra:
        callenv.update(extra)
    base.with_suffix('.invocation.json').write_text(json.dumps({'command':cmd,'cwd':str(cwd),'scenario_environment':extra or {}}, indent=2)+'\n')
    p = subprocess.run(cmd, cwd=cwd, env=callenv, capture_output=True)
    base.with_suffix('.stdout').write_bytes(p.stdout)
    base.with_suffix('.stderr').write_bytes(p.stderr)
    base.with_suffix('.exit.json').write_text(json.dumps({'exit':p.returncode})+'\n')
    if p.returncode != 0:
        raise RuntimeError(f'{label}: exit {p.returncode}; see {base}')
    return p.stdout.decode(), str(base.relative_to(root))

def write_json(path, data):
    path.write_text(json.dumps(data,indent=2)+'\n')

def parse_json(text):
    return json.loads(text[text.index('{'):])

npmv = subprocess.check_output(['npm','--version'],text=True).strip()
fixtures = {}
for scenario, globals_ in [('implicit-attributes',['global.json']),('global-lock',['package-lock.json','global.json']),('global-package',['packages/a/shared.json','global.json']),('nonglobal-package',['global.json']),('ordinary-lock',['global.json'])]:
    fixture=root/'fixtures'/scenario
    if fixture.exists():
        raise RuntimeError(f'Fixture already exists: {fixture}')
    fixture.mkdir(parents=True)
    for pkg in ['a','b']:
        d=fixture/'packages'/pkg
        (d/'src').mkdir(parents=True)
        data={'name':pkg,'version':'1.0.0','scripts':{'build':'echo build','test':'echo test'}}
        if scenario=='ordinary-lock' and pkg=='a':
            data['dependencies']={'is-odd':'3.0.0'}
        write_json(d/'package.json',data)
        (d/'src/value.js').write_text('export const value = 1;\n')
        write_json(d/'shared.json',{'value':1})
    write_json(fixture/'package.json',{'name':'selection-repro','private':True,'packageManager':'npm@'+npmv,'workspaces':['packages/*']})
    write_json(fixture/'turbo.json',{'$schema':'https://turborepo.dev/schema.json','globalDependencies':globals_,'tasks':{'build':{'inputs':['src/**'],'outputs':[]},'test':{'inputs':['$TURBO_DEFAULT$'],'outputs':[]}}})
    write_json(fixture/'global.json',{'value':1})
    (fixture/'.gitattributes').write_text('* text=auto\n')
    (fixture/'.gitignore').write_text('node_modules\n.turbo\n')
    run(['npm','--userconfig','/dev/null','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],fixture,scenario+'-lock')
    if scenario=='ordinary-lock':
        p=fixture/'packages/a/package.json'
        m=json.loads(p.read_text());m['dependencies']['is-odd']='^3.0.0';write_json(p,m)
        run(['npm','--userconfig','/dev/null','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],fixture,scenario+'-range-lock')
    run(['git','init','-q','-b','main'],fixture,scenario+'-git-init')
    run(['git','config','user.name','repro'],fixture,scenario+'-git-name')
    run(['git','config','user.email','repro@example.invalid'],fixture,scenario+'-git-email')
    run(['git','config','maintenance.auto','false'],fixture,scenario+'-git-maintenance')
    run(['git','add','-A'],fixture,scenario+'-add')
    run(['git','commit','-q','-m','baseline'],fixture,scenario+'-commit')
    baseline=run(['git','rev-parse','HEAD'],fixture,scenario+'-base')[0].strip()
    arms={'no-edit':baseline}
    if scenario=='implicit-attributes':
        (fixture/'.gitattributes').write_text('* text=auto\n*.md text\n')
        trigger='attributes-only'
    elif scenario=='global-lock':
        with (fixture/'package-lock.json').open('a') as f:f.write('\n')
        trigger='lock-newline-only'
    elif scenario in ['global-package','nonglobal-package']:
        write_json(fixture/'packages/a/shared.json',{'value':2})
        trigger='package-file-only'
    else:
        run(['npm','--userconfig','/dev/null','update','is-odd','--workspace','a','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],fixture,scenario+'-resolution-update')
        trigger='resolution-only'
    run(['git','add','-A'],fixture,scenario+'-trigger-add')
    run(['git','diff','--cached','--name-status'],fixture,scenario+'-trigger-diff')
    run(['git','commit','-q','-m',trigger],fixture,scenario+'-trigger-commit')
    arms[trigger]=run(['git','rev-parse','HEAD'],fixture,scenario+'-trigger-head')[0].strip()
    run(['git','checkout','-q','--detach',baseline],fixture,scenario+'-base-checkout-root')
    write_json(fixture/'global.json',{'value':2})
    run(['git','commit','-q','-am','root-global-only'],fixture,scenario+'-root-commit')
    arms['root-global-only']=run(['git','rev-parse','HEAD'],fixture,scenario+'-root-head')[0].strip()
    run(['git','checkout','-q','--detach',baseline],fixture,scenario+'-base-checkout-source')
    (fixture/'packages/a/src/value.js').write_text('export const value = 2;\n')
    run(['git','commit','-q','-am','ordinary-source-only'],fixture,scenario+'-source-commit')
    arms['ordinary-source-only']=run(['git','rev-parse','HEAD'],fixture,scenario+'-source-head')[0].strip()
    fixtures[scenario]={'path':str(fixture),'base':baseline,'arms':arms}
write_json(evidence/'fixtures.json',fixtures)
all_results=[]
repeat_results=[]
for version in args.versions:
    prefix=root/'tools'/('turbo-'+version)
    prefix.mkdir(parents=True,exist_ok=True)
    run(['npm','--userconfig','/dev/null','install','--prefix',str(prefix),'--save-exact','--no-audit','--no-fund','turbo@'+version],root,'install-'+version)
    binary=str(prefix/'node_modules/.bin/turbo')
    actual=run([binary,'--skip-infer','--version'],root,'version-'+version)[0].strip()
    for scenario, data in fixtures.items():
        fixture=Path(data['path']);baseline=data['base']
        run(['git','checkout','-q','--detach',baseline],fixture,version+'-'+scenario+'-baseline')
        run([binary,'--skip-infer','info'],fixture,version+'-'+scenario+'-info')
        for arm,head in data['arms'].items():
            run(['git','checkout','-q','--detach',head],fixture,version+'-'+scenario+'-'+arm+'-checkout')
            diff=run(['git','diff','--name-only',baseline,head],fixture,version+'-'+scenario+'-'+arm+'-diff')[0].splitlines()
            dry,dp=run([binary,'--skip-infer','run','build','test','--dry=json'],fixture,version+'-'+scenario+'-'+arm+'-all')
            query,qp=run([binary,'--skip-infer','query','affected','--tasks','build','test','--base',baseline,'--head',head],fixture,version+'-'+scenario+'-'+arm+'-query')
            selected,sp=run([binary,'--skip-infer','run','build','test','--affected','--dry=json'],fixture,version+'-'+scenario+'-'+arm+'-affected',{'TURBO_SCM_BASE':baseline,'TURBO_SCM_HEAD':head})
            plan=parse_json(dry);q=parse_json(query);sel=parse_json(selected)
            hashes={t['taskId']:t['hash'] for t in plan['tasks']}
            globals_=plan.get('globalCacheInputs',{})
            row={'version':version,'actual_version':actual,'scenario':scenario,'arm':arm,'base':baseline,'head':head,'changed_paths':diff,'hashes':hashes,'globalCacheInputs':globals_,'query':q,'affected_task_ids':[t['taskId'] for t in sel['tasks']],'evidence':{'dry':dp,'query':qp,'affected':sp}}
            all_results.append(row)
            write_json(evidence/'observations.json',all_results)
            print(json.dumps({k:row[k] for k in ['version','scenario','arm','changed_paths','hashes','query','affected_task_ids']}),flush=True)

        run(['git','checkout','-q','--detach',baseline],fixture,version+'-'+scenario+'-no-edit-repeat-checkout')
        repeat_raw, repeat_path=run([binary,'--skip-infer','run','build','test','--dry=json'],fixture,version+'-'+scenario+'-no-edit-repeat')
        repeat_hashes={t['taskId']:t['hash'] for t in parse_json(repeat_raw)['tasks']}
        first=next(x['hashes'] for x in all_results if x['version']==version and x['scenario']==scenario and x['arm']=='no-edit')
        repeat_results.append({'version':version,'scenario':scenario,'hashes':repeat_hashes,'matches_initial_baseline':repeat_hashes==first,'evidence':repeat_path})
        write_json(evidence/'no-edit-repeat.json',repeat_results)
