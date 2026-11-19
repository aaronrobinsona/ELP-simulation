"""What does ONE ranger do when two poaching incidents happen at the same time?

Exploratory script. dzanga_sim.py is NOT modified, and no dispatch rule is added.

The baseline sim has unlimited rangers: every detected poacher gets its own
ranger from the nearest town, so incidents never compete. Here the only change
is a limit of N rangers (default 1), starting at the first town(s). When the
ranger is busy, newly detected poachers wait. When it becomes free it takes the
next incident in the order the sim itself flagged them (_scan_mics loop order).
That ordering is the sim's own; nothing else decides.

Logged per tie (2+ incidents waiting when the ranger becomes free): which
poacher the ranger took, which were left waiting, distances from the ranger,
and what happened to the ones left waiting.
"""
import argparse, csv, os, time
from multiprocessing import Pool
import dzanga_sim as ds
from dzanga_sim import m2px, norm2, safe_unit

KM_PER_PX = ds.METERS_PER_PIXEL / 1000.0


class OneRangerSim(ds.DzangaSimulation):
    def setup(self, n_rangers):
        towns = self.repulsors
        self.rangers = [dict(x=towns[i % len(towns)].x, y=towns[i % len(towns)].y, task=None)
                        for i in range(n_rangers)]
        self.queue = []                 # poacher indices, in the order the sim flagged them
        self.seen = set()
        self.detect_t, self.assign_t = {}, {}
        self.kills = {}                 # poacher index -> elephants poached
        self.ties = []

    def _scan_mics(self):
        super()._scan_mics()            # baseline detection/alert logic, unchanged
        for i, p in enumerate(self.poachers):
            if p.is_targeted and not p.is_caught and i not in self.seen:
                self.seen.add(i)
                self.queue.append(i)
                self.detect_t[i] = self.current_sim_time

    def _move_rangers(self, step_r):
        self.queue = [i for i in self.queue if not self.poachers[i].is_caught]
        for r in self.rangers:
            if r['task'] is None and self.queue:
                i = self.queue.pop(0)   # next in the sim's own detection order
                if self.queue:          # a tie: others are still waiting
                    d = lambda j: round(norm2(self.poachers[j].x - r['x'],
                                              self.poachers[j].y - r['y']) * KM_PER_PX, 1)
                    self.ties.append(dict(t_h=round(self.current_sim_time / 3600, 2),
                                          chose=i, chose_km=d(i),
                                          waiting=list(self.queue),
                                          waiting_km=[d(j) for j in self.queue]))
                r['task'] = i
                self.assign_t[i] = self.current_sim_time
        for r in self.rangers:
            if r['task'] is None:
                continue
            p = self.poachers[r['task']]
            if p.is_caught:
                r['task'] = None
                continue
            p.ranger_x, p.ranger_y = r['x'], r['y']
            dx, dy = p.x - r['x'], p.y - r['y']
            if norm2(dx, dy) < m2px(500):
                p.is_caught = True
                p.caught_time = self.current_sim_time
                r['task'] = None
            else:
                ux, uy = safe_unit(dx, dy)
                r['x'] += ux * step_r
                r['y'] += uy * step_r

    def _poaching_check(self):
        before = {k for k, e in enumerate(self.elephants) if e.is_poached}
        events = super()._poaching_check()      # baseline poaching logic, unchanged
        for k, e in enumerate(self.elephants):
            if e.is_poached and k not in before:  # attribute to the nearest free poacher
                j = min((j for j, p in enumerate(self.poachers) if not p.is_caught),
                        key=lambda j: norm2(self.poachers[j].x - e.x, self.poachers[j].y - e.y))
                self.kills[j] = self.kills.get(j, 0) + 1
        return events


def run(args):
    n_poachers, n_rangers, seed, days, dt = args
    ds.NUM_POACHERS = n_poachers
    sim = OneRangerSim(mic_strategy=1, num_mics=80, seed=seed)
    sim.setup(n_rangers)
    T = days * 86400
    while (sim.current_sim_time < T and sim.caught_count < len(sim.poachers)
           and sim.poached_count < len(sim.elephants)):
        sim.step(dt, 1.0)
    for tie in sim.ties:                # what happened to the ones left waiting
        tie['waiting_caught'] = sum(sim.poachers[j].is_caught for j in tie['waiting'])
        tie['waiting_kills_total'] = sum(sim.kills.get(j, 0) for j in tie['waiting'])
        tie.update(poachers=n_poachers, rangers=n_rangers, seed=seed)
    waits = [sim.assign_t[i] - sim.detect_t[i] for i in sim.assign_t]
    summary = dict(poachers=n_poachers, rangers=n_rangers, seed=seed,
                   poached=sim.poached_count, caught=sim.caught_count, detected=len(sim.seen),
                   never_reached=len(sim.seen) - len(sim.assign_t),
                   ties=len(sim.ties),
                   mean_wait_h=round(sum(waits) / len(waits) / 3600, 2) if waits else 0.0,
                   kills_by_detected=sum(sim.kills.get(i, 0) for i in sim.seen),
                   kills_by_undetected=sum(v for i, v in sim.kills.items() if i not in sim.seen))
    return summary, sim.ties


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
    ap.add_argument('--poachers', default='30,100', help='comma list of poacher counts')
    ap.add_argument('--rangers', type=int, default=1)
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--days', type=float, default=1.0, help='sim-days per run')
    ap.add_argument('--dt', type=float, default=10.0, help='sim-seconds per step (README uses 1 for paper runs)')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--out', default='results/one_ranger')
    a = ap.parse_args()
    jobs = [(P, a.rangers, s, a.days, a.dt) for P in map(int, a.poachers.split(',')) for s in range(a.seeds)]
    t = time.time()
    with Pool(a.workers) as pool:
        out = pool.map(run, jobs)
    summaries = [s for s, _ in out]
    ties = [x for _, tl in out for x in tl]
    write(a.out + '_summary.csv', summaries)
    write(a.out + '_ties.csv', ties)
    print(f'{len(jobs)} runs in {time.time()-t:.0f}s -> {a.out}_summary.csv, {a.out}_ties.csv\n')
    cols = list(summaries[0].keys())[3:]
    print(f"{'P':>5}{'R':>3}{'seed':>5}" + ''.join(f'{c:>20}' for c in cols))
    for s in summaries:
        print(f"{s['poachers']:>5}{s['rangers']:>3}{s['seed']:>5}" + ''.join(f'{s[c]:>20}' for c in cols))
    print(f'\nTies (ranger free, 2+ incidents waiting): {len(ties)}')
    for x in ties[:10]:
        print(f"  P={x['poachers']} seed={x['seed']} t={x['t_h']}h: took poacher {x['chose']} "
              f"({x['chose_km']} km away); left waiting {x['waiting']} at {x['waiting_km']} km "
              f"-> {x['waiting_caught']} of them caught later, {x['waiting_kills_total']} elephants killed by them")


if __name__ == '__main__':
    main()
