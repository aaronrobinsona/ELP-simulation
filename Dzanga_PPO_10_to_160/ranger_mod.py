"""One ranger vs. two poaching incidents at the same time.

The ONLY change to the sim: at most one ranger can be out at once.
  - The sim's own code still decides everything else: detection, alerts, which
    town the ranger leaves from (nearest town to the poacher, as in the
    baseline), the chase, the catch, poaching.
  - If the sim flags a poacher while the ranger is already out, that dispatch
    simply doesn't happen (no queue, no priority). The poacher stays free; if a
    mic detects it again after the ranger is back, the sim dispatches as usual.
  - If the sim flags two poachers in the SAME scan, the one the sim's own loop
    reaches first gets the ranger (mic order). That order is the sim's, not ours.

Scenario: 2 poachers, each placed on a mic ~--sep-km apart, with an elephant
~1 km from each mic, so both incidents trigger at the same moment.
Each seed is run twice: unmodified sim vs. one-ranger sim.
"""
import argparse, math
import dzanga_sim as ds
from dzanga_sim import m2px, norm2

KM = ds.METERS_PER_PIXEL / 1000.0


class OneRanger(ds.DzangaSimulation):
    def _scan_mics(self):
        before = {i for i, p in enumerate(self.poachers) if p.is_targeted}
        super()._scan_mics()                      # unchanged baseline logic
        busy = any(p.is_targeted and not p.is_caught
                   for i, p in enumerate(self.poachers) if i in before)
        for i, p in enumerate(self.poachers):     # in the sim's own order
            if p.is_targeted and i not in before:
                if busy:                          # ranger already out: no dispatch
                    p.is_targeted = False
                    p.ranger_x = p.ranger_y = p.base_x = p.base_y = -999.0
                else:
                    busy = True


def build(cls, seed, sep_km):
    ds.NUM_POACHERS = 2
    sim = cls(mic_strategy=1, num_mics=80, seed=seed)
    mics = sim.mics
    best = min(((a, b) for a in range(len(mics)) for b in range(a + 1, len(mics))),
               key=lambda ab: abs(norm2(mics[ab[0]].x - mics[ab[1]].x,
                                        mics[ab[0]].y - mics[ab[1]].y) * KM - sep_km))
    for k, mi in enumerate(best):
        m = mics[mi]
        p, e = sim.poachers[k], sim.elephants[k]
        p.x, p.y = m.x, m.y                       # poacher on the mic
        for ang in range(0, 360, 15):             # elephant ~1 km away, inside the park
            ex = m.x + m2px(1000) * math.cos(math.radians(ang))
            ey = m.y + m2px(1000) * math.sin(math.radians(ang))
            if sim.is_inside_park(ex, ey):
                e.x, e.y = ex, ey
                break
    return sim, best


def town(sim, x, y):
    return min(sim.repulsors, key=lambda z: norm2(x - z.x, y - z.y)).name


def run(cls, seed, sep_km, days, dt):
    sim, pair = build(cls, seed, sep_km)
    log, dispatched, caught = [], set(), set()
    poached_before = 0
    T = days * 86400
    while sim.current_sim_time < T and sim.caught_count < 2 and sim.poached_count < 20:
        sim.step(dt, 1.0)
        t = sim.current_sim_time / 3600
        for i, p in enumerate(sim.poachers):
            if p.is_targeted and i not in dispatched:
                dispatched.add(i)
                log.append(f'{t:6.2f} h  ranger dispatched to poacher {i} from '
                           f'{town(sim, p.base_x, p.base_y)} '
                           f'({norm2(p.x - p.base_x, p.y - p.base_y) * KM:.1f} km)')
            if p.is_caught and i not in caught:
                caught.add(i)
                log.append(f'{t:6.2f} h  poacher {i} caught')
        if sim.poached_count > poached_before:
            for _ in range(sim.poached_count - poached_before):
                log.append(f'{t:6.2f} h  elephant poached')
            poached_before = sim.poached_count
    return sim, pair, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seeds', type=int, default=5)
    ap.add_argument('--sep-km', type=float, default=20.0, help='distance between the two incidents')
    ap.add_argument('--days', type=float, default=2.0)
    ap.add_argument('--dt', type=float, default=1.0)
    a = ap.parse_args()
    rows = []
    for seed in range(a.seeds):
        for name, cls in (('unmodified', ds.DzangaSimulation), ('one ranger', OneRanger)):
            sim, pair, log = run(cls, seed, a.sep_km, a.days, a.dt)
            print(f'--- seed {seed} | {name} | mics {pair} ---')
            print('\n'.join(log[:8]) or '   (no events)')
            rows.append((seed, name, sim.caught_count, sim.poached_count,
                         round(sim.current_sim_time / 3600, 1)))
    print(f"\n{'seed':>4}  {'sim':12}{'caught (of 2)':>15}{'poached':>9}{'ended at (h)':>14}")
    for r in rows:
        print(f'{r[0]:>4}  {r[1]:12}{r[2]:>15}{r[3]:>9}{r[4]:>14}')


if __name__ == '__main__':
    main()
