#!/usr/bin/env python3
import argparse, json, os, subprocess, sys, time
from pathlib import Path

PROBLEMS = Path(__file__).parent / 'problems'
RUNS = Path(__file__).parent / 'runs'

def load_problem(fp: Path):
    d = json.loads(Path(fp).read_text(encoding='utf-8'))
    for k in ('id','description'):
        if k not in d:
            raise ValueError('problem file missing key: ' + k)
    return d

def write_workspace(prob: dict) -> Path:
    ts = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    wd = RUNS / prob['id'] / ts
    wd.mkdir(parents=True, exist_ok=True)
    for rel, content in prob.get('setup_files', prob.get('input_files', {})).items():
        p = wd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
    (wd / 'problem.json').write_text(json.dumps(prob, indent=2), encoding='utf-8')
    return wd

def run_cmd(cmd: str, cwd: Path, timeout: int):
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True, text=True, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = 124, '', 'TIMEOUT'
    dur = round(time.perf_counter() - start, 4)
    return {'returncode': rc, 'stdout': out, 'stderr': err, 'duration_sec': dur}


def run_one(pfile: Path, agent_cmd: str or None, t_agent: int, t_test: int):
    prob = load_problem(pfile)
    wd = write_workspace(prob)
    if agent_cmd:
        run_cmd(agent_cmd.replace('{workdir}', str(wd)), wd, t_agent)
    ver = run_cmd(prob['test_command'], wd, t_test)
    return prob['id'], ver['returncode'] == 0, ver

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--problems-dir', type=Path, default=PROBLEMS)
    ap.add_argument('--runs-dir', type=Path, default=RUNS)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_list = sub.add_parser('list')
    p_run = sub.add_parser('run')
    g = p_run.add_mutually_exclusive_group(required=False)
    g.add_argument('--id'); g.add_argument('--all', action='store_true')
    p_run.add_argument('--agent-cmd'); p_run.add_argument('--timeout-agent', type=int, default=120); p_run.add_argument('--timeout-test', type=int, default=30)
    args = ap.parse_args()

    problems_dir = args.problems_dir
    runs_dir = args.runs_dir

    if args.cmd == 'list':
        for p in sorted(problems_dir.glob('*.json')):
            d = load_problem(p)
            print(str(d['id']) + ': ' + d['description'])
        return 0

    if args.cmd == 'run':
        files = [problems_dir / (args.id + '.json')] if args.id else sorted(problems_dir.glob('*.json'))
        ok = 0
        t0 = time.perf_counter()
        for pf in files:
            d = load_problem(pf)
            print('\n=== Running ' + d['id'] + ' ===')
            pid, passed, ver = run_one(pf, args.agent_cmd, args.timeout_agent, args.timeout_test)
            print('Result: ' + ('PASS' if passed else 'FAIL') + ' | verify=' + str(ver['duration_sec']) + 's')
            ok += 1 if passed else 0
        print('\nSummary: ' + str(ok) + '/' + str(len(files)) + ' passed in ' + str(round(time.perf_counter()-t0,3)) + 's')
        return 0 if ok == len(files) else 2

if __name__ == '__main__':
    sys.exit(main())
