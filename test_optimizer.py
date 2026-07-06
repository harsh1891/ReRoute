import datetime
from app.generator import generate_flight_schedule, generate_passengers_and_bookings, generate_disruption
from app.optimizer import ReAccommodationOptimizer
from app.rule_engine import RuleEngine
import dimod

flights = generate_flight_schedule(num_days=2)
passengers = generate_passengers_and_bookings(flights, total_passengers=10)
canceled_ids, impacted = generate_disruption(flights, passengers, flights_to_cancel=2)

print(f"Impacted passengers: {[p.pnr for p in impacted]}")
for p in impacted:
    print(f"Passenger {p.pnr} ({p.pnr_type}): original class {p.original_class}")

rule_engine = RuleEngine()
optimizer = ReAccommodationOptimizer(flights, passengers, canceled_ids, rule_engine)
optimizer.generate_candidate_options(K=3)

# Print options
for pnr, opts in optimizer.passenger_options.items():
    print(f"\nOptions for {pnr}:")
    for i, opt in enumerate(opts):
        print(f"  Opt {i}: {opt['itinerary'].flight_ids} class {opt['assigned_class']} cost {opt['cost']:.2f}")

print("\n--- Solving MILP ---")
milp_res = optimizer.solve_constrained_milp()
print("MILP Status:", milp_res['status'])
print("MILP Objective:", milp_res['objective_value'])
print("MILP Accommodated:", milp_res['accommodated'])
print("MILP Exceptions:", milp_res['exceptions'])

print("\n--- Solving CQM ---")
# Let's inspect the CQM
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
    unaccommodated_penalty = 10000.0 + optimizer.rule_engine.get_passenger_priority_score(p)
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
    constraint_expr = sum(vars_list)
    cqm.add_constraint(constraint_expr <= float(f.available_capacity(cls)), label=f"cap_{fid}_{cls}")

# Solve BQM
bqm, invert = dimod.cqm_to_bqm(cqm, lagrange_multiplier=1500.0)
sampler = dimod.SimulatedAnnealingSampler()
sampleset = sampler.sample(bqm, num_reads=50)

print("\nSamples returned by Sampler (first 5):")
for i, (sample, energy) in enumerate(sampleset.data(['sample', 'energy'])):
    if i >= 5: break
    feasible = cqm.check_feasible(sample)
    # Calculate objective
    cqm_obj_val = cqm.objective.energy(sample)
    print(f"Sample {i}: energy={energy:.2f}, feasible={feasible}, cqm_obj={cqm_obj_val:.2f}")
    # Print non-zero vars
    non_zero = {k: v for k, v in sample.items() if v > 0.5}
    print(f"  Non-zero variables: {non_zero}")
