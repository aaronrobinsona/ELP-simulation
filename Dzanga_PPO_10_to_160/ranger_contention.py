"""Observe the UNMODIFIED sim when many poachers trigger incidents at the same time.

Nothing about the sim's behavior is changed: no ranger limit, no dispatch rule,
no subclassing. The only input changed is the number of poachers. The script
steps the original DzangaSimulation and only READS its state after each step.

Note: the sim has no ranger count. Each detected poacher gets its own ranger,
dispatched from the town nearest that poacher. So "one ranger choosing between
two incidents" cannot happen in the sim as written. What this script records is
how often that situation WOULD arise:
  - simultaneous incidents: 2+ poachers flagged in the same step
  - town overload: 2+ rangers out at once from the SAME town (if that town had
    only one ranger, someone would have had to choose)
"""
import argparse, csv, os, time
from multiprocessing import Pool
import dzanga_sim as ds
from dzanga_sim import norm2

KM_PER_PX = ds.METERS_PER_PIXEL / 1000.0


def town_of(sim, p):
    return min(sim.repulsors, key=lambda z: norm2(p.base_x - z.x, p.base_y - z.y)).name


def run(args):
    n_poachers, seed, days, dt = args
    ds.NUM_POACHERS = n_poachers
    sim = ds.DzangaSimulation(mic_strategy=1, num_mics=80, seed=seed)
    T = days * 86400
    seen = set()
    events = []
    max_active = max_same_town = simultaneous_steps = 0
    while (sim.current_sim_time < T and sim.caught_count < len(sim.poachers)
           and sim.poached_count < len(sim.elephants)):
        sim.step(dt, 1.0)
        new = [i for i, p in enumerate(sim.poachers) if p.is_targeted and i not in seen]
        seen.update(new)
        if len(new) >= 2:
            simultaneous_steps += 1
            events.append(dict(
                poachers=n_poachers, seed=seed, t_h=round(sim.current_sim_time / 3600, 2),
                incidents=len(new),
                towns=';'.join(town_of(sim, sim.poachers[i]) for i in new),
                dist_km=';'.join(str(round(norm2(sim.poachers[i].x - sim.poachers[i].base_x,
                                                 sim.poachers[i].y - sim.poachers[i].base_y)
                                           * KM_PER_PX, 1)) for i in new),
                poacher_ids=';'.join(map(str, new))))
        active = [p for p in sim.poachers if p.is_targeted and not p.is_caught]
        max_active = max(max_active, len(active))
        per_town = {}
        for p in active:
            t = town_of(sim, p)
            per_town[t] = per_town.get(t, 0) + 1
        max_same_town = max(max_same_town, max(per_town.values(), default=0))
    for e in events:
        ids = map(int, e['poacher_ids'].split(';'))
        e['caught_after_h'] = ';'.join(
            str(round((sim.poachers[i].caught_time - e['t_h'] * 3600) / 3600, 2))
            if sim.poachers[i].is_caught else 'not caught' for i in ids)
    summary = dict(poachers=n_poachers, seed=seed, poached=sim.poached_count,
                   caught=sim.caught_count, detected=len(seen),
                   simultaneous_steps=simultaneous_steps,
                   max_rangers_out=max_active, max_rangers_out_same_town=max_same_town,
                   sim_days=round(sim.current_sim_time / 86400, 2))
    return summary, events


def write(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--poachers', default='10,30,100', help='comma list of poacher counts')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--days', type=float, default=1.0, help='sim-days per run')
    ap.add_argument('--dt', type=float, default=10.0, help='sim-seconds per step (README uses 1 for paper runs)')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--out', default='results/observe')
    a = ap.parse_args()
    jobs = [(P, s, a.days, a.dt) for P in map(int, a.poachers.split(',')) for s in range(a.seeds)]
    t = time.time()
    with Pool(a.workers) as pool:
        out = pool.map(run, jobs)
    summaries = [s for s, _ in out]
    events = [e for _, ev in out for e in ev]
    write(a.out + '_summary.csv', summaries)
    write(a.out + '_simultaneous.csv', events)
    print(f'{len(jobs)} runs in {time.time()-t:.0f}s -> {a.out}_summary.csv, {a.out}_simultaneous.csv\n')
    cols = list(summaries[0].keys())[2:]
    print(f"{'P':>5}{'seed':>5}" + ''.join(f'{c:>27}' for c in cols))
    for s in summaries:
        print(f"{s['poachers']:>5}{s['seed']:>5}" + ''.join(f'{s[c]:>27}' for c in cols))
    print(f'\nSimultaneous incidents (2+ poachers flagged in the same step): {len(events)}')
    for e in events[:10]:
        print(f"  P={e['poachers']} seed={e['seed']} t={e['t_h']}h: {e['incidents']} incidents, "
              f"rangers from {e['towns']}, {e['dist_km']} km from town, caught after (h): {e['caught_after_h']}")


if __name__ == '__main__':
    main()
