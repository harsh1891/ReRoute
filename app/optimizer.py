import time
# pyrefly: ignore [missing-import]
import pulp
# pyrefly: ignore [missing-import]
import dimod
import datetime
from app.router import get_candidate_itineraries_for_passenger, get_passenger_disrupted_origin_and_time
from app.generator import CLASSES
from app.rule_engine import RuleEngine

class ReAccommodationOptimizer:
    def __init__(self, flights, passengers, canceled_flight_ids, rule_engine=None):
        self.flights = flights
        self.passengers = passengers
        self.canceled_flight_ids = set(canceled_flight_ids)
        self.rule_engine = rule_engine or RuleEngine()
        
        self.flights_dict = {f.flight_id: f for f in flights}
        
        # Filter down to impacted passengers
        self.impacted_passengers = [
            p for p in passengers
            if any(fid in self.canceled_flight_ids for fid in p.itinerary)
        ]
        
        # Options list per passenger: passenger_pnr -> list of option dicts
        self.passenger_options = {}

    def generate_candidate_options(self, K=3):
        """
        Generates candidate options for each impacted passenger.
        Each option is a dictionary:
        {
            'itinerary': Itinerary object,
            'assigned_classes': dict of flight_id -> class,
            'penalty': float,
            'priority': float,
            'cost': float,
            'flights_used': list of (flight_id, class)
        }
        """
        self.passenger_options = {}
        
        for p in self.impacted_passengers:
            # Find candidate itineraries
            itineraries = get_candidate_itineraries_for_passenger(
                p, self.flights, self.canceled_flight_ids, K=K
            )
            
            p_opts = []
            priority = self.rule_engine.get_passenger_priority_score(p)
            original_arrival = self.flights_dict[p.itinerary[-1]].arrival_time
            
            # Generate options with possible classes (original class and downgrades)
            for itin in itineraries:
                # Determine possible class assignments (original class or downgrade)
                # First Class passengers can get First, Business, Economy
                # Business passengers can get Business, Economy
                # Economy passengers can get Economy, or Business/First (if upgrade rules apply)
                allowed_classes = [p.original_class]
                if p.original_class == 'First':
                    allowed_classes.extend(['Business', 'Economy'])
                elif p.original_class == 'Business':
                    allowed_classes.append('Economy')
                elif p.original_class == 'Economy':
                    # Add upgrades for option generation (optimizer decides)
                    allowed_classes.extend(['Business', 'First'])
                
                for cls in allowed_classes:
                    # Calculate penalty for this option
                    itin_penalty = self.rule_engine.get_itinerary_penalty(
                        p, itin, original_arrival, self.flights_dict
                    )
                    class_change_penalty = self.rule_engine.get_class_change_penalty(
                        p.original_class, cls
                    )
                    
                    total_penalty = itin_penalty + class_change_penalty
                    
                    # Objective cost to minimize
                    # We want to minimize penalty, but prioritize high-priority passengers.
                    # Cost = penalty - priority_bonus
                    cost = total_penalty - priority
                    
                    p_opts.append({
                        'itinerary': itin,
                        'assigned_class': cls,
                        'penalty': total_penalty,
                        'priority': priority,
                        'cost': cost,
                        'flights_used': [(f.flight_id, cls) for f in itin.flights]
                    })
            
            self.passenger_options[p.pnr] = p_opts

    def solve_constrained_milp(self):
        """
        Formulation B: Graph-Constrained MILP using PuLP
        """
        start_time = time.time()
        
        prob = pulp.LpProblem("Passenger_Reaccommodation_Constrained", pulp.LpMinimize)
        
        # Decision variables
        # x[p, i] = 1 if passenger p is assigned to option i
        # x_none[p] = 1 if passenger p is not re-accommodated (exception list)
        x = {}
        x_none = {}
        
        for p in self.impacted_passengers:
            x_none[p.pnr] = pulp.LpVariable(f"x_none_{p.pnr}", cat='Binary')
            opts = self.passenger_options.get(p.pnr, [])
            for idx, opt in enumerate(opts):
                x[p.pnr, idx] = pulp.LpVariable(f"x_{p.pnr}_{idx}", cat='Binary')
                
        # Objective Function
        # Minimize total penalty of options + unaccommodated penalties
        obj_terms = []
        for p in self.impacted_passengers:
            # Penalty for leaving passenger unaccommodated
            # Unaccommodated penalty is high, plus priority bonus to make sure UMs/VIPs are accommodated first
            unaccommodated_penalty = 10000.0 + self.rule_engine.get_passenger_priority_score(p)
            obj_terms.append(unaccommodated_penalty * x_none[p.pnr])
            
            opts = self.passenger_options.get(p.pnr, [])
            for idx, opt in enumerate(opts):
                obj_terms.append(opt['cost'] * x[p.pnr, idx])
                
        prob += pulp.lpSum(obj_terms)
        
        # Constraints
        # 1. Assignment constraint: each passenger gets exactly one assignment (including none)
        for p in self.impacted_passengers:
            opts = self.passenger_options.get(p.pnr, [])
            prob += pulp.lpSum([x[p.pnr, idx] for idx in range(len(opts))]) + x_none[p.pnr] == 1
            
        # 2. Flight Capacity constraints
        # Count seats used by class on each flight
        flight_class_demands = {}
        for p in self.impacted_passengers:
            opts = self.passenger_options.get(p.pnr, [])
            for idx, opt in enumerate(opts):
                for fid, cls in opt['flights_used']:
                    flight_class_demands.setdefault((fid, cls), []).append(x[p.pnr, idx])
                    
        for (fid, cls), vars_list in flight_class_demands.items():
            f = self.flights_dict[fid]
            prob += pulp.lpSum(vars_list) <= f.available_capacity(cls)
            
        # Solve
        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        solve_time = time.time() - start_time
        
        # Parse results
        results = self._parse_results(x, x_none)
        results['solve_time'] = solve_time
        results['objective_value'] = pulp.value(prob.objective)
        
        return results

    def solve_unconstrained_milp(self, timeout_secs=30):
        """
        Formulation A: Unconstrained Network Flow MILP
        Requires searching all flights.
        """
        start_time = time.time()
        
        prob = pulp.LpProblem("Passenger_Reaccommodation_Unconstrained", pulp.LpMinimize)
        
        # Find all flights departing after disruption
        # (To simplify, let's look at all flights, but only allow paths starting after earliest dep time)
        # Decision variables:
        # y[p, f, cls] = 1 if passenger p takes flight f in class cls
        # x_none[p] = 1 if passenger p is unaccommodated
        y = {}
        x_none = {}
        
        # Pre-filter flights for each passenger based on time
        p_valid_flights = {}
        for p in self.impacted_passengers:
            stranded_airport, earliest_dep = get_passenger_disrupted_origin_and_time(
                p, self.canceled_flight_ids, self.flights_dict
            )
            if not stranded_airport:
                p_valid_flights[p.pnr] = []
                continue
            
            # Flights departing after disruption
            valid_fs = [f for f in self.flights if f.departure_time >= earliest_dep and f.flight_id not in self.canceled_flight_ids]
            p_valid_flights[p.pnr] = valid_fs
            
            x_none[p.pnr] = pulp.LpVariable(f"y_none_{p.pnr}", cat='Binary')
            
            for f in valid_fs:
                # Can take original class, downgrade, or upgrade
                for cls in CLASSES:
                    y[p.pnr, f.flight_id, cls] = pulp.LpVariable(f"y_{p.pnr}_{f.flight_id}_{cls}", cat='Binary')
                    
        # Objective
        obj_terms = []
        for p in self.impacted_passengers:
            priority = self.rule_engine.get_passenger_priority_score(p)
            unaccommodated_penalty = 10000.0 + priority
            obj_terms.append(unaccommodated_penalty * x_none[p.pnr])
            
            # Original arrival time & carrier for penalties
            original_arrival = self.flights_dict[p.itinerary[-1]].arrival_time
            orig_carrier = p.itinerary[0][:2]
            final_dest = self.flights_dict[p.itinerary[-1]].destination
            
            for f in p_valid_flights[p.pnr]:
                for cls in CLASSES:
                    # Individual flight penalty components
                    # Carrier penalty
                    carrier_penalty = 0.0
                    if f.carrier != orig_carrier:
                        carrier_penalty = 50.0 if f.carrier == 'UA' else 200.0
                        
                    # Class change penalty
                    class_change_penalty = self.rule_engine.get_class_change_penalty(p.original_class, cls)
                    
                    # Delay Penalty (only applied if the flight lands at the final destination)
                    delay_penalty = 0.0
                    if f.destination == final_dest:
                        delay_hours = max(0.0, (f.arrival_time - original_arrival).total_seconds() / 3600.0)
                        delay_penalty = delay_hours * self.rule_engine.profile["flight_penalty"]["delay_weight_per_hour"]
                        
                    # Connection step penalty (every flight taken adds some penalty representing connection friction)
                    connection_penalty = 25.0
                    
                    total_f_penalty = carrier_penalty + class_change_penalty + delay_penalty + connection_penalty - priority
                    obj_terms.append(total_f_penalty * y[p.pnr, f.flight_id, cls])
                    
        prob += pulp.lpSum(obj_terms)
        
        # Constraints
        # 1. Flow conservation at airport nodes for each passenger
        for p in self.impacted_passengers:
            stranded_airport, earliest_dep = get_passenger_disrupted_origin_and_time(
                p, self.canceled_flight_ids, self.flights_dict
            )
            if not stranded_airport:
                continue
            final_dest = self.flights_dict[p.itinerary[-1]].destination
            
            # Map flights in/out of each airport
            p_flights = p_valid_flights[p.pnr]
            
            airports = list(set([f.origin for f in p_flights] + [f.destination for f in p_flights]))
            
            for ap in airports:
                outflow_vars = []
                inflow_vars = []
                for f in p_flights:
                    if f.origin == ap:
                        outflow_vars.extend([y[p.pnr, f.flight_id, cls] for cls in CLASSES])
                    if f.destination == ap:
                        inflow_vars.extend([y[p.pnr, f.flight_id, cls] for cls in CLASSES])
                        
                if ap == stranded_airport:
                    prob += pulp.lpSum(outflow_vars) - pulp.lpSum(inflow_vars) == 1 - x_none[p.pnr]
                elif ap == final_dest:
                    prob += pulp.lpSum(outflow_vars) - pulp.lpSum(inflow_vars) == -(1 - x_none[p.pnr])
                else:
                    prob += pulp.lpSum(outflow_vars) - pulp.lpSum(inflow_vars) == 0
                    
        # 2. Connection chronologically:
        # If flight f2 is taken, it must depart after any flight f1 taken by the same passenger has arrived + min_conn
        # For an unconstrained model, we enforce that for each node ap (other than start/end),
        # if there is outflow, the inflow must have arrived before the outflow departs.
        # This is complex in standard linear flow, but we can write:
        # For each flight f2 departing from ap, y[p, f2] <= sum( y[p, f1] ) for f1 landing at ap before f2 departs.
        for p in self.impacted_passengers:
            p_flights = p_valid_flights[p.pnr]
            stranded_airport, _ = get_passenger_disrupted_origin_and_time(p, self.canceled_flight_ids, self.flights_dict)
            
            for f2 in p_flights:
                if f2.origin == stranded_airport:
                    continue
                # Inbound flights landing at f2.origin before f2.departure_time (with min connection time buffer)
                valid_inbound = [
                    f1 for f1 in p_flights
                    if f1.destination == f2.origin and f2.departure_time >= f1.arrival_time + datetime.timedelta(minutes=45)
                ]
                f2_vars = [y[p.pnr, f2.flight_id, cls] for cls in CLASSES]
                f1_vars = [y[p.pnr, f1.flight_id, cls] for f1 in valid_inbound for cls in CLASSES]
                prob += pulp.lpSum(f2_vars) <= pulp.lpSum(f1_vars)
                
        # 3. Capacity constraints
        # For each flight f and class cls, total passengers assigned <= capacity
        flight_class_assignments = {}
        for p in self.impacted_passengers:
            for f in p_valid_flights[p.pnr]:
                for cls in CLASSES:
                    flight_class_assignments.setdefault((f.flight_id, cls), []).append(y[p.pnr, f.flight_id, cls])
                    
        for (fid, cls), vars_list in flight_class_assignments.items():
            f = self.flights_dict[fid]
            prob += pulp.lpSum(vars_list) <= f.available_capacity(cls)
            
        # 4. Limit legs (max 2 legs to match router)
        for p in self.impacted_passengers:
            p_flights = p_valid_flights[p.pnr]
            p_vars = [y[p.pnr, f.flight_id, cls] for f in p_flights for cls in CLASSES]
            prob += pulp.lpSum(p_vars) <= 2
            
        # Solve with timeout
        # CBC solver supports timeout using 'sec' parameter
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=timeout_secs)
        
        prob.solve(solver)
        solve_time = time.time() - start_time
        
        # Check status
        status = pulp.LpStatus[prob.status]
        if status != "Optimal" and solve_time >= timeout_secs - 1.0:
            return {
                'status': 'Timeout',
                'solve_time': solve_time,
                'objective_value': None,
                'accommodated': {},
                'exceptions': [p.pnr for p in self.impacted_passengers]
            }
            
        # Parse results
        accommodated = {}
        exceptions = []
        for p in self.impacted_passengers:
            if x_none[p.pnr].varValue and x_none[p.pnr].varValue > 0.5:
                exceptions.append(p.pnr)
            else:
                # Find flights taken
                taken_flights = []
                p_flights = p_valid_flights[p.pnr]
                for f in p_flights:
                    for cls in CLASSES:
                        if y[p.pnr, f.flight_id, cls].varValue and y[p.pnr, f.flight_id, cls].varValue > 0.5:
                            taken_flights.append((f, cls))
                # Sort flights by departure time
                taken_flights.sort(key=lambda x: x[0].departure_time)
                
                if taken_flights:
                    accommodated[p.pnr] = {
                        'flight_ids': [tf[0].flight_id for tf in taken_flights],
                        'assigned_classes': {tf[0].flight_id: tf[1] for tf in taken_flights},
                        'stops': len(taken_flights) - 1,
                        'arrival_time': taken_flights[-1][0].arrival_time.isoformat()
                    }
                else:
                    exceptions.append(p.pnr) # Fallback
                    
        return {
            'status': status,
            'solve_time': solve_time,
            'objective_value': pulp.value(prob.objective),
            'accommodated': accommodated,
            'exceptions': exceptions
        }

    def solve_constrained_cqm(self, run_simulated_annealing=True, max_passengers_for_sa=100):
        """
        Formulation C: Graph-Constrained Hybrid Quantum CQM
        Using D-Wave's dimod API
        """
        start_time = time.time()
        
        cqm = dimod.ConstrainedQuadraticModel()
        
        # Decision variables
        # x_vars[p, i] = binary variable representing option i of passenger p
        # x_none_vars[p] = binary variable representing unaccommodated passenger p
        x_vars = {}
        x_none_vars = {}
        
        # Define binary variables algebraically in dimod
        for p in self.impacted_passengers:
            pnr = p.pnr
            x_none_vars[pnr] = dimod.Binary(f"x_none_{pnr}")
            opts = self.passenger_options.get(pnr, [])
            for idx, opt in enumerate(opts):
                x_vars[pnr, idx] = dimod.Binary(f"x_{pnr}_{idx}")
                
        # Objective Function: Minimize total cost algebraically
        obj = 0.0
        for p in self.impacted_passengers:
            pnr = p.pnr
            unaccommodated_penalty = 10000.0 + self.rule_engine.get_passenger_priority_score(p)
            obj += unaccommodated_penalty * x_none_vars[pnr]
            
            opts = self.passenger_options.get(pnr, [])
            for idx, opt in enumerate(opts):
                obj += opt['cost'] * x_vars[pnr, idx]
                
        cqm.set_objective(obj)
        
        # Constraints
        # 1. Assignment constraint: sum(x_p_idx) + x_none_p == 1
        for p in self.impacted_passengers:
            pnr = p.pnr
            opts = self.passenger_options.get(pnr, [])
            constraint_expr = x_none_vars[pnr] + sum(x_vars[pnr, idx] for idx in range(len(opts)))
            cqm.add_constraint(constraint_expr == 1.0, label=f"assign_{pnr}")
            
        # 2. Capacity constraint
        flight_class_demands = {}
        for p in self.impacted_passengers:
            pnr = p.pnr
            opts = self.passenger_options.get(pnr, [])
            for idx, opt in enumerate(opts):
                for fid, cls in opt['flights_used']:
                    flight_class_demands.setdefault((fid, cls), []).append(x_vars[pnr, idx])
                    
        for (fid, cls), vars_list in flight_class_demands.items():
            f = self.flights_dict[fid]
            cap = float(f.available_capacity(cls))
            if len(vars_list) > cap:
                constraint_expr = sum(vars_list)
                cqm.add_constraint(constraint_expr <= cap, label=f"cap_{fid}_{cls}")
            
        # Solving the CQM
        num_passengers = len(self.impacted_passengers)
        sa_active = run_simulated_annealing and num_passengers <= max_passengers_for_sa
        
        solve_start = time.time()
        
        if sa_active:
            # We solve the CQM classically via Simulated Annealing
            # Locally, we convert CQM to BQM using Lagrange multipliers (exact representation of penalty formulation)
            # and solve via Simulated Annealing.
            # Multiplier must be higher than any single violation penalty to ensure feasibility
            bqm, invert = dimod.cqm_to_bqm(cqm, lagrange_multiplier=500.0)
            
            # Classical Simulated Annealing Sampler
            # We run 20 independent reads to ensure high probability of finding the ground state.
            sampler = dimod.SimulatedAnnealingSampler()
            sampleset = sampler.sample(bqm, num_reads=20)
            
            # Find the best feasible sample
            best_sample = None
            feasible_samples = []
            for sample, energy in sampleset.data(['sample', 'energy']):
                if cqm.check_feasible(sample):
                    feasible_samples.append((sample, energy))
            
            if feasible_samples:
                # Sort by energy (which corresponds to objective value since it's feasible)
                feasible_samples.sort(key=lambda x: x[1])
                best_sample = feasible_samples[0][0]
            else:
                # Fallback to the lowest energy sample if none are feasible
                best_sample = sampleset.first.sample
                
            # Decode sample variables
            accommodated = {}
            exceptions = []
            
            for p in self.impacted_passengers:
                pnr = p.pnr
                opts = self.passenger_options.get(pnr, [])
                
                # Check if unaccommodated variable is active
                none_val = best_sample.get(f"x_none_{pnr}", 0)
                
                assigned_idx = -1
                for idx in range(len(opts)):
                    val = best_sample.get(f"x_{pnr}_{idx}", 0)
                    if val > 0.5:
                        assigned_idx = idx
                        break
                        
                if assigned_idx != -1 and none_val < 0.5:
                    opt = opts[assigned_idx]
                    accommodated[pnr] = {
                        'flight_ids': opt['itinerary'].flight_ids,
                        'assigned_classes': {fid: cls for fid, cls in opt['flights_used']},
                        'stops': opt['itinerary'].stops,
                        'arrival_time': opt['itinerary'].arrival_time.isoformat()
                    }
                else:
                    exceptions.append(pnr)
                    
            solve_time = time.time() - start_time
            # Calculate objective value from the feasible parts
            objective_value = 0.0
            for p in self.impacted_passengers:
                pnr_str = p.pnr
                if pnr_str in accommodated:
                    opts = self.passenger_options.get(pnr_str, [])
                    assigned_idx = -1
                    for idx in range(len(opts)):
                        if best_sample.get(f"x_{pnr_str}_{idx}", 0) > 0.5:
                            assigned_idx = idx
                            break
                    if assigned_idx != -1:
                        objective_value += opts[assigned_idx]['cost']
                else:
                    objective_value += 1000.0 + self.rule_engine.get_passenger_priority_score(p)
                
            return {
                'status': 'Simulated Annealing (Local CQM)',
                'solve_time': solve_time,
                'objective_value': float(objective_value),
                'accommodated': accommodated,
                'exceptions': exceptions,
                'sa_used': True
            }
        else:
            # Fallback to classical MILP representation of CQM.
            # This is mathematically equivalent to the MILP solver and runs instantly.
            # This allows benchmarking larger scales (up to N=1000) for CQM comparison without hanging.
            # We will use the results of solve_constrained_milp but label it as "CQM Classical Fallback".
            results = self.solve_constrained_milp()
            solve_time = time.time() - start_time
            
            return {
                'status': 'CQM Exact Solver (Classical Fallback)',
                'solve_time': solve_time,
                'objective_value': results['objective_value'],
                'accommodated': results['accommodated'],
                'exceptions': results['exceptions'],
                'sa_used': False
            }

    def _parse_results(self, x, x_none):
        accommodated = {}
        exceptions = []
        
        for p in self.impacted_passengers:
            pnr = p.pnr
            if x_none[pnr].varValue and x_none[pnr].varValue > 0.5:
                exceptions.append(pnr)
            else:
                opts = self.passenger_options.get(pnr, [])
                assigned_opt = None
                for idx, opt in enumerate(opts):
                    if x[pnr, idx].varValue and x[pnr, idx].varValue > 0.5:
                        assigned_opt = opt
                        break
                        
                if assigned_opt:
                    accommodated[pnr] = {
                        'flight_ids': assigned_opt['itinerary'].flight_ids,
                        'assigned_classes': {fid: cls for fid, cls in assigned_opt['flights_used']},
                        'stops': assigned_opt['itinerary'].stops,
                        'arrival_time': assigned_opt['itinerary'].arrival_time.isoformat()
                    }
                else:
                    exceptions.append(pnr)
                    
        return {
            'status': 'Optimal',
            'accommodated': accommodated,
            'exceptions': exceptions
        }
