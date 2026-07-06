import datetime
from app.generator import generate_flight_schedule, generate_passengers_and_bookings, generate_disruption
from app.optimizer import ReAccommodationOptimizer
from app.rule_engine import RuleEngine
import dimod

flights = generate_flight_schedule(num_days=2)
passengers = generate_passengers_and_bookings(flights, total_passengers=10)
canceled_ids, impacted = generate_disruption(flights, passengers, flights_to_cancel=2)

rule_engine = RuleEngine()
optimizer = ReAccommodationOptimizer(flights, passengers, canceled_ids, rule_engine)
optimizer.generate_candidate_options(K=3)

# Build CQM
cqm = dimod.ConstrainedQuadraticModel()
x_vars = {}
x_none_vars = {}

for p in optimizer.impacted_passengers:
    pnr = p.pnr
    x_none_vars[pnr] = dimod.Binary(f"x_none_{pnr}")
    opts = optimizer.passenger_options.get(pnr, [])
    for idx, opt in enumerate(opts):
        x_vars[pnr, idx] = dimod.Binary(f"x_{pnr}_{idx}")
        
obj = 0.0
for p in optimizer.impacted_passengers:
    pnr = p.pnr
    unaccommodated_penalty = 1000.0 + optimizer.rule_engine.get_passenger_priority_score(p)
    obj += unaccommodated_penalty * x_none_vars[pnr]
    
    opts = optimizer.passenger_options.get(pnr, [])
    for idx, opt in enumerate(opts):
        obj += opt['cost'] * x_vars[pnr, idx]
        
cqm.set_objective(obj)

for p in optimizer.impacted_passengers:
    pnr = p.pnr
    opts = optimizer.passenger_options.get(pnr, [])
    constraint_expr = x_none_vars[pnr] + sum(x_vars[pnr, idx] for idx in range(len(opts)))
    cqm.add_constraint(constraint_expr == 1.0, label=f"assign_{pnr}")
    
flight_class_demands = {}
for p in optimizer.impacted_passengers:
    pnr = p.pnr
    opts = optimizer.passenger_options.get(pnr, [])
    for idx, opt in enumerate(opts):
        for fid, cls in opt['flights_used']:
            flight_class_demands.setdefault((fid, cls), []).append(x_vars[pnr, idx])
            
for (fid, cls), vars_list in flight_class_demands.items():
    f = optimizer.flights_dict[fid]
    cap = float(f.available_capacity(cls))
    if len(vars_list) > cap:
        constraint_expr = sum(vars_list)
        cqm.add_constraint(constraint_expr <= cap, label=f"cap_{fid}_{cls}")

print("\n=== CQM OBJECTIVE ===")
print(cqm.objective)

print("\n=== CQM CONSTRAINTS ===")
for label, constraint in cqm.constraints.items():
    print(f"{label}: {constraint}")

# Solve MILP for comparison
print("\n=== MILP SOLUTIONS ===")
milp_res = optimizer.solve_constrained_milp()
print("MILP Objective:", milp_res['objective_value'])
print("MILP Accommodated:", milp_res['accommodated'])

# Let's inspect the BQM conversion
print("\n=== BQM CONVERSION ===")
bqm, invert = dimod.cqm_to_bqm(cqm, lagrange_multiplier=500.0)
print(f"BQM variable types: {bqm.vartype}")
print("\n=== BQM LINEAR COEFFICIENTS ===")
for v, coeff in bqm.linear.items():
    print(f"  {v}: {coeff:.2f}")
print("\n=== BQM QUADRATIC COEFFICIENTS ===")
for (v1, v2), coeff in bqm.quadratic.items():
    print(f"  ({v1}, {v2}): {coeff:.2f}")
    
# Solve using classical simulated annealing
sampler = dimod.SimulatedAnnealingSampler()
sampleset = sampler.sample(bqm, num_reads=100)

print("\nSamples returned by Sampler:")
for i, (sample, energy) in enumerate(sampleset.data(['sample', 'energy'])):
    if i >= 5: break
    feasible = cqm.check_feasible(sample)
    cqm_obj_val = cqm.objective.energy(sample)
    print(f"Sample {i}: energy={energy:.2f}, feasible={feasible}, cqm_obj={cqm_obj_val:.2f}")
    non_zero = {k: v for k, v in sample.items() if v > 0.5}
    print(f"  Non-zero variables: {non_zero}")

# Test the energy of the optimal state in BQM
test_sample = {k: 0.0 for k in bqm.variables}
test_sample['x_PNR100001_2'] = 1.0
test_sample['x_PNR100002_2'] = 1.0
print("\n=== BQM ENERGY OF OPTIMAL STATE ===")
print("Energy:", bqm.energy(test_sample))
print("Is Feasible in CQM:", cqm.check_feasible(test_sample))
print("CQM Objective Energy:", cqm.objective.energy(test_sample))
