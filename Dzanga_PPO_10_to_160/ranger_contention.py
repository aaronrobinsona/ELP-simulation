"""Finite-ranger contention experiment on top of the unmodified dzanga_sim.py.

Baseline sim: every detected poacher gets its own ranger (unlimited).
Exploratory script; dzanga_sim.py is NOT modified.
Here: R rangers stationed round-robin across the 5 towns. Detected poachers
join an incident queue; a free ranger is assigned by POLICY:
  fifo    - oldest incident first (order received), nearest free ranger takes it
  nearest - globally closest (free ranger, incident) pair first
A ranger stays where it caught its poacher and is free again immediately.
"""
import argparse, csv, itertools, time
from multiprocessing import Pool
import dzanga_sim as ds
from dzanga_sim import m2px, norm2, safe_unit


class LimitedRangerSim(ds.DzangaSimulation):
    def setup(self, n_rangers, policy):
        self.policy = policy
        towns = self.repulsors
        self.rangers = [dict(x=towns[i % len(towns)].x, y=towns[i % len(towns)].y, task=None)
                        for i in range(n_rangers)]
        self.queue = []          # (time_detected, poacher_index)
        self.queued = set()
        self.waits = []          # detection -> ranger assigned (s)
        self.contention_steps = 0  # steps with a waiting incident and no free ranger
        self.max_queue = 0
        self.tie_events = 0      # steps where >=2 incidents waited for 1 free ranger

    def _scan_mics(self):
        super()._scan_mics()     # baseline detection/alert logic sets p.is_targeted
        for i, p in enumerate(self.poachers):
            if p.is_targeted and not p.is_caught and i not in self.queued:
                self.queued.add(i)
                self.queue.append((self.current_sim_time, i))

    def _assign(self):
        free = [r for r in self.rangers if r['task'] is None]
        waiting = [q for q in self.queue if not self.poachers[q[1]].is_caught]
        self.queue = waiting
        if len(waiting) >= 2 and len(free) == 1:
            self.tie_events += 1
        while free and self.queue:
            if self.policy == 'fifo':
                t0, i = min(self.queue)
                p = self.poachers[i]
                r = min(free, key=lambda r: norm2(r['x'] - p.x, r['y'] - p.y))
            else:  # nearest pair
                (t0, i), r = min(itertools.product(self.queue, free),
                                 key=lambda qr: norm2(qr[1]['x'] - self.poachers[qr[0][1]].x,
                                                      qr[1]['y'] - self.poachers[qr[0][1]].y))
            r['task'] = i
            self.waits.append(self.current_sim_time - t0)
            self.queue.remove((t0, i)); free.remove(r)
        if self.queue:
            self.contention_steps += 1
            self.max_queue = max(self.max_queue, len(self.queue))

    def _move_rangers(self, step_r):
        self._assign()
        for r in self.rangers:
            if r['task'] is None:
                continue
            p = self.poachers[r['task']]
            if p.is_caught:
                r['task'] = None; continue
            dx, dy = p.x - r['x'], p.y - r['y']
            if norm2(dx, dy) < m2px(500):
                p.is_caught = True; p.caught_time = self.current_sim_time
                r['task'] = None
            else:
                ux, uy = safe_unit(dx, dy)
                r['x'] += ux * step_r; r['y'] += uy * step_r
        for r in self.rangers:          # keep GUI fields roughly sensible
            if r['task'] is not None:
                self.poachers[r['task']].ranger_x = r['x']; self.poachers[r['task']].ranger_y = r['y']


def run(args):
    n_poachers, n_rangers, policy, seed, sim_days, dt = args
    ds.NUM_POACHERS = n_poachers
    sim = LimitedRangerSim(mic_strategy=1, num_mics=80, seed=seed)
    sim.setup(n_rangers, policy)
    T = sim_days * 86400
    while (sim.current_sim_time < T and sim.caught_count < len(sim.poachers)
           and sim.poached_count < len(sim.elephants)):
        sim.step(dt, 1.0)
    w = sim.waits
    return dict(poachers=n_poachers, rangers=n_rangers, policy=policy, seed=seed,
                poached=sim.poached_count, caught=sim.caught_count,
                detected=len(sim.queued), mean_wait_h=round(sum(w) / len(w) / 3600, 2) if w else 0,
                max_queue=sim.max_queue, tie_events=sim.tie_events,
                sim_days=round(sim.current_sim_time / 86400, 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--poachers', default='30,100', help='comma list of poacher counts')
    ap.add_argument('--rangers', default='1,3', help='comma list of ranger counts')
    ap.add_argument('--policies', default='fifo,nearest')
    ap.add_argument('--seeds', type=int, default=2)
    ap.add_argument('--days', type=float, default=1.0, help='sim-days per run')
    ap.add_argument('--dt', type=float, default=10.0, help='sim-seconds per step (README uses 1 for paper runs)')
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--csv', default='results/ranger_contention.csv')
    a = ap.parse_args()
    jobs = [(P, R, pol, s, a.days, a.dt)
            for P in map(int, a.poachers.split(',')) for R in map(int, a.rangers.split(','))
            for pol in a.policies.split(',') for s in range(a.seeds)]
    t = time.time()
    with Pool(a.workers) as pool:
        rows = pool.map(run, jobs)
    import os; os.makedirs(os.path.dirname(a.csv) or '.', exist_ok=True)
    with open(a.csv, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print(f'{len(rows)} runs in {time.time()-t:.0f}s -> {a.csv}\n')
    groups = {}
    for r in rows:
        groups.setdefault((r['poachers'], r['rangers'], r['policy']), []).append(r)
    cols = ['poached', 'caught', 'detected', 'mean_wait_h', 'max_queue', 'tie_events']
    print(f"{'P':>5}{'R':>4} {'policy':8}" + ''.join(f'{c:>12}' for c in cols))
    for k in sorted(groups):
        v = groups[k]
        print(f'{k[0]:>5}{k[1]:>4} {k[2]:8}' + ''.join(f'{sum(x[c] for x in v)/len(v):>12.2f}' for c in cols))


if __name__ == '__main__':
    main()
