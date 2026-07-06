from flask import Flask, jsonify, request, render_template
import os
import time
import json
from app.generator import generate_flight_schedule, generate_passengers_and_bookings, generate_disruption
from app.optimizer import ReAccommodationOptimizer
from app.rule_engine import RuleEngine
from app.benchmark import run_benchmark

app = Flask(__name__, 
            template_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'templates')),
            static_folder=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'static')))

# Global state for schedule and bookings
FLIGHTS = []
PASSENGERS = []
CANCELED_FLIGHT_IDS = []
IMPACTED_PASSENGERS = []

def init_data():
    global FLIGHTS, PASSENGERS, CANCELED_FLIGHT_IDS, IMPACTED_PASSENGERS
    # Generate schedule and bookings on startup (1,000 passengers default scale)
    FLIGHTS = generate_flight_schedule(num_days=2)
    PASSENGERS = generate_passengers_and_bookings(FLIGHTS, total_passengers=1000)
    CANCELED_FLIGHT_IDS, IMPACTED_PASSENGERS = generate_disruption(FLIGHTS, PASSENGERS, flights_to_cancel=2)
    print(f"Server initialized with {len(FLIGHTS)} flights and {len(PASSENGERS)} passengers.")
    print(f"Disrupted flight IDs: {CANCELED_FLIGHT_IDS}")
    print(f"Number of impacted passengers: {len(IMPACTED_PASSENGERS)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    return jsonify({
        'flights': [f.to_dict() for f in FLIGHTS],
        'canceled_flight_ids': list(CANCELED_FLIGHT_IDS),
        'total_passengers': len(PASSENGERS),
        'impacted_passengers_count': len(IMPACTED_PASSENGERS),
        'impacted_passengers': [p.to_dict() for p in IMPACTED_PASSENGERS]
    })

@app.route('/api/optimize', methods=['POST'])
def run_optimize():
    data = request.json or {}
    solver_type = data.get('solver_type', 'milp') # 'milp' or 'cqm'
    profile = data.get('rule_profile', None)
    
    # Initialize rule engine with profile from UI
    rule_engine = RuleEngine(profile)
    
    # Initialize optimizer with global schedule & disruptions
    optimizer = ReAccommodationOptimizer(FLIGHTS, PASSENGERS, CANCELED_FLIGHT_IDS, rule_engine)
    
    # 1. Generate options
    start_time = time.time()
    optimizer.generate_candidate_options(K=3)
    router_time = time.time() - start_time
    
    # 2. Solve
    if solver_type == 'cqm':
        # Solve constrained CQM
        # For server responsiveness, we run simulated annealing on server side if N_impacted <= 50,
        # otherwise we use the exact solver fallback to ensure the server doesn't hang.
        res = optimizer.solve_constrained_cqm(run_simulated_annealing=True, max_passengers_for_sa=50)
    else:
        # Solve constrained MILP
        res = optimizer.solve_constrained_milp()
        
    solve_time = res['solve_time']
    accommodated = res['accommodated']
    exceptions = res['exceptions']
    
    # 3. Compute flight-level default solution vs exception list
    # The default flight level solution maps CanceledFlight -> AlternateFlight
    # It covers passengers where the majority on that canceled flight are re-accommodated to the same alternate flight.
    # We group accommodated passengers by their canceled flight and their assigned alternate flight.
    canceled_to_assigned = {}
    passenger_mapping = {}
    
    for pnr, acc in accommodated.items():
        # Find passenger object
        p_obj = next(p for p in PASSENGERS if p.pnr == pnr)
        
        # Find which of their original flights was canceled
        canceled_fid = next(fid for fid in p_obj.itinerary if fid in CANCELED_FLIGHT_IDS)
        
        # Find their primary new flight (the first leg of their alternative itinerary)
        new_fid = acc['flight_ids'][0]
        
        canceled_to_assigned.setdefault(canceled_fid, {}).setdefault(new_fid, []).append(pnr)
        passenger_mapping[pnr] = {
            'canceled_flight': canceled_fid,
            'assigned_itinerary': acc['flight_ids'],
            'assigned_classes': acc['assigned_classes'],
            'stops': acc['stops'],
            'arrival_time': acc['arrival_time'],
            'class': p_obj.original_class,
            'assigned_class': acc['assigned_classes'][new_fid],
            'pnr_type': p_obj.pnr_type,
            'name': p_obj.name
        }
        
    default_flight_solution = {}
    flight_exceptions = []
    
    for canceled_fid, target_flights in canceled_to_assigned.items():
        # Find the flight where the majority was sent
        sorted_targets = sorted(target_flights.items(), key=lambda x: len(x[1]), reverse=True)
        if sorted_targets:
            majority_new_fid, majority_pnrs = sorted_targets[0]
            majority_pnr_set = set(majority_pnrs)
            
            default_flight_solution[canceled_fid] = {
                'alternate_flight_id': majority_new_fid,
                'passengers_count': len(majority_pnrs),
                'pnr_list': majority_pnrs
            }
            
            # The passengers on this canceled flight who were NOT accommodated on this majority flight
            # are classified as exceptions.
            for new_fid, pnrs in sorted_targets[1:]:
                for pnr in pnrs:
                    flight_exceptions.append({
                        'pnr': pnr,
                        'reason': f"Re-routed to non-default flight {new_fid} to optimize path or class",
                        'details': passenger_mapping[pnr]
                    })
                    
    # Also add unaccommodated passengers to exceptions
    for pnr in exceptions:
        p_obj = next(p for p in PASSENGERS if p.pnr == pnr)
        canceled_fid = next(fid for fid in p_obj.itinerary if fid in CANCELED_FLIGHT_IDS)
        flight_exceptions.append({
            'pnr': pnr,
            'reason': "No suitable alternative flight with available capacity was found",
            'details': {
                'canceled_flight': canceled_fid,
                'name': p_obj.name,
                'pnr_type': p_obj.pnr_type,
                'class': p_obj.original_class,
                'assigned_itinerary': [],
                'assigned_class': None,
                'stops': 0,
                'arrival_time': None
            }
        })
        
    # Write the solution files to the data directory (so they can be downloaded)
    solutions_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'static', 'data'))
    os.makedirs(solutions_dir, exist_ok=True)
    
    with open(os.path.join(solutions_dir, 'flight_default_reaccommodation.json'), 'w') as f:
        json.dump(default_flight_solution, f, indent=4)
        
    with open(os.path.join(solutions_dir, 'passenger_exception_reaccommodation.json'), 'w') as f:
        json.dump(flight_exceptions, f, indent=4)
        
    return jsonify({
        'status': 'Success',
        'solver_status': res['status'],
        'sa_used': res.get('sa_used', False),
        'solve_time_seconds': solve_time,
        'router_time_seconds': router_time,
        'objective_value': res['objective_value'],
        'stats': {
            'total_passengers': len(PASSENGERS),
            'impacted': len(IMPACTED_PASSENGERS),
            'accommodated': len(accommodated),
            'exceptions': len(flight_exceptions),
            'unaccommodated': len(exceptions),
            'success_rate': (len(accommodated) / len(IMPACTED_PASSENGERS) * 100.0) if IMPACTED_PASSENGERS else 0.0
        },
        'default_flight_solution': default_flight_solution,
        'exceptions': flight_exceptions,
        'passenger_mapping': passenger_mapping
    })

@app.route('/api/benchmark', methods=['POST'])
def trigger_benchmark():
    data = request.json or {}
    scales = data.get('scales', [10, 50, 100, 200])
    
    # Run the benchmark
    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'static', 'data', 'benchmark_results.json'))
    bench_data = run_benchmark(scales=scales, timeout_secs=30, output_path=output_path)
    
    return jsonify(bench_data)

@app.route('/api/benchmark-results', methods=['GET'])
def get_benchmark_results():
    output_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'static', 'data', 'benchmark_results.json'))
    if os.path.exists(output_path):
        with open(output_path, 'r') as f:
            return jsonify(json.load(f))
    else:
        # Generate default benchmark results if they don't exist
        # We can run it on scales [10, 50, 100] to initialize it quickly
        bench_data = run_benchmark(scales=[10, 50, 100], timeout_secs=30, output_path=output_path)
        return jsonify(bench_data)

init_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
