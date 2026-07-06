import datetime
import random

# Set random seed for reproducibility
random.seed(42)

AIRPORTS = {
    'hubs': ['ORD', 'DFW', 'DEN', 'JFK', 'LAX'],
    'spokes': ['SEA', 'SFO', 'MIA', 'BOS', 'LAS', 'PHX', 'CLT', 'MSP', 'DTW', 'IAH']
}

CARRIERS = ['AA', 'UA', 'DL']  # AA is primary carrier, UA is partner, DL is competitor
PNR_TYPES = ['UM', 'Employee', 'VIP', 'Platinum', 'Gold', 'Silver', 'Standard']
CLASSES = ['First', 'Business', 'Economy']
ANCILLARIES = ['Wifi', 'ExtraLegroom', 'Meal', 'Lounge']

class Flight:
    def __init__(self, flight_id, carrier, origin, destination, departure_time, arrival_time, cap_first, cap_biz, cap_eco):
        self.flight_id = flight_id
        self.carrier = carrier
        self.origin = origin
        self.destination = destination
        self.departure_time = departure_time  # datetime
        self.arrival_time = arrival_time      # datetime
        self.capacities = {
            'First': cap_first,
            'Business': cap_biz,
            'Economy': cap_eco
        }
        self.bookings = {
            'First': 0,
            'Business': 0,
            'Economy': 0
        }

    def available_capacity(self, service_class):
        return max(0, self.capacities[service_class] - self.bookings[service_class])

    def to_dict(self):
        return {
            'flight_id': self.flight_id,
            'carrier': self.carrier,
            'origin': self.origin,
            'destination': self.destination,
            'departure_time': self.departure_time.isoformat(),
            'arrival_time': self.arrival_time.isoformat(),
            'capacity_first': self.capacities['First'],
            'capacity_biz': self.capacities['Business'],
            'capacity_eco': self.capacities['Economy'],
            'bookings_first': self.bookings['First'],
            'bookings_biz': self.bookings['Business'],
            'bookings_eco': self.bookings['Economy']
        }

class Passenger:
    def __init__(self, pnr, name, pnr_type, original_class, itinerary, special_assistance=False, ancillaries=None):
        self.pnr = pnr
        self.name = name
        self.pnr_type = pnr_type  # 'UM', 'Employee', 'VIP', 'Platinum', 'Gold', 'Silver', 'Standard'
        self.original_class = original_class  # 'First', 'Business', 'Economy'
        self.itinerary = itinerary  # list of flight_ids
        self.special_assistance = special_assistance
        self.ancillaries = ancillaries or []  # subset of ['Wifi', 'ExtraLegroom', 'Meal', 'Lounge']

    def to_dict(self):
        return {
            'pnr': self.pnr,
            'name': self.name,
            'pnr_type': self.pnr_type,
            'original_class': self.original_class,
            'itinerary': self.itinerary,
            'special_assistance': self.special_assistance,
            'ancillaries': self.ancillaries
        }


def generate_flight_schedule(start_date=None, num_days=2):
    if start_date is None:
        start_date = datetime.datetime(2026, 7, 4, 0, 0, 0)
    
    flights = []
    flight_counter = 100
    
    hubs = AIRPORTS['hubs']
    spokes = AIRPORTS['spokes']
    
    # Generate flights over the days
    for day in range(num_days):
        current_day = start_date + datetime.timedelta(days=day)
        
        # Hub-to-Hub flights: frequent connections
        for origin in hubs:
            for dest in hubs:
                if origin == dest:
                    continue
                # Generate 4 flights per day per pair
                for hour in [6, 11, 16, 21]:
                    dep_time = current_day.replace(hour=hour, minute=0, second=0)
                    duration = datetime.timedelta(hours=3) # standard 3hr hub-to-hub
                    arr_time = dep_time + duration
                    
                    carrier = 'AA' if random.random() < 0.7 else random.choice(['UA', 'DL'])
                    flight_id = f"{carrier}{flight_counter}"
                    flight_counter += 1
                    
                    # Hub flights have larger aircraft
                    flights.append(Flight(
                        flight_id=flight_id,
                        carrier=carrier,
                        origin=origin,
                        destination=dest,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        cap_first=12,
                        cap_biz=24,
                        cap_eco=150
                    ))
        
        # Hub-to-Spoke and Spoke-to-Hub flights
        for spoke in spokes:
            for hub in hubs:
                # 2 flights per day Spoke -> Hub
                for hour in [7, 15]:
                    dep_time = current_day.replace(hour=hour, minute=random.randint(0, 45))
                    duration = datetime.timedelta(hours=2, minutes=30)
                    arr_time = dep_time + duration
                    
                    carrier = 'AA' if random.random() < 0.6 else random.choice(['UA', 'DL'])
                    flight_id = f"{carrier}{flight_counter}"
                    flight_counter += 1
                    
                    flights.append(Flight(
                        flight_id=flight_id,
                        carrier=carrier,
                        origin=spoke,
                        destination=hub,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        cap_first=8,
                        cap_biz=16,
                        cap_eco=120
                    ))
                
                # 2 flights per day Hub -> Spoke
                for hour in [10, 18]:
                    dep_time = current_day.replace(hour=hour, minute=random.randint(0, 45))
                    duration = datetime.timedelta(hours=2, minutes=30)
                    arr_time = dep_time + duration
                    
                    carrier = 'AA' if random.random() < 0.6 else random.choice(['UA', 'DL'])
                    flight_id = f"{carrier}{flight_counter}"
                    flight_counter += 1
                    
                    flights.append(Flight(
                        flight_id=flight_id,
                        carrier=carrier,
                        origin=hub,
                        destination=spoke,
                        departure_time=dep_time,
                        arrival_time=arr_time,
                        cap_first=8,
                        cap_biz=16,
                        cap_eco=120
                    ))
                    
    return flights


def generate_passengers_and_bookings(flights, total_passengers=1000):
    passengers = []
    
    # We want to place bookings on these flights
    pnr_counter = 100000
    
    # Create helper structures to find flights by origin
    flights_by_origin = {}
    for f in flights:
        flights_by_origin.setdefault(f.origin, []).append(f)
        
    generated = 0
    attempts = 0
    max_attempts = total_passengers * 10
    
    # Names database for realism
    first_names = ["John", "Mary", "David", "Linda", "James", "Patricia", "Robert", "Barbara", "Michael", "Elizabeth", "William", "Jennifer"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez"]
    
    while generated < total_passengers and attempts < max_attempts:
        attempts += 1
        
        # Decide itinerary: 70% Direct, 30% Connecting
        itinerary_type = 'Direct' if random.random() < 0.7 else 'Connecting'
        
        # Select origins and destinations
        all_airports = AIRPORTS['hubs'] + AIRPORTS['spokes']
        origin = random.choice(all_airports)
        dest = random.choice(all_airports)
        while origin == dest:
            dest = random.choice(all_airports)
            
        pnr_type = random.choices(
            PNR_TYPES,
            weights=[0.02, 0.03, 0.05, 0.10, 0.15, 0.25, 0.40], # UM, Employee, VIP, Plat, Gold, Silver, Standard
            k=1
        )[0]
        
        original_class = random.choices(
            CLASSES,
            weights=[0.05, 0.15, 0.80], # First, Biz, Eco
            k=1
        )[0]
        
        special_assistance = random.random() < 0.02 # 2% need assistance
        
        # Generate ancillaries
        ancillaries = []
        if original_class == 'First':
            ancillaries = ['Wifi', 'Meal', 'Lounge']
        elif original_class == 'Business':
            ancillaries = random.sample(ANCILLARIES, k=random.randint(1, 3))
        else:
            ancillaries = random.sample(ANCILLARIES, k=random.randint(0, 2))
            
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        
        itinerary = []
        
        if itinerary_type == 'Direct':
            # Find a flight from origin to destination
            valid_flights = [f for f in flights_by_origin.get(origin, []) if f.destination == dest]
            if not valid_flights:
                continue
            
            # Select one flight, check if capacity exists
            flight = random.choice(valid_flights)
            if flight.available_capacity(original_class) > 0:
                flight.bookings[original_class] += 1
                itinerary = [flight.flight_id]
        else:
            # Connecting itinerary. Since we have hub-and-spoke:
            # If origin is spoke, connect at hub.
            # If origin is hub, go to hub, then spoke.
            # Find a hub to connect
            possible_hubs = AIRPORTS['hubs']
            hub = random.choice(possible_hubs)
            while hub == origin or hub == dest:
                hub = random.choice(possible_hubs)
                
            # Flight 1: origin -> hub
            f1_list = [f for f in flights_by_origin.get(origin, []) if f.destination == hub]
            if not f1_list:
                continue
            f1 = random.choice(f1_list)
            
            # Flight 2: hub -> dest, departing after flight 1 arrival + connection window
            min_conn = datetime.timedelta(minutes=45)
            max_conn = datetime.timedelta(hours=6)
            
            f2_list = [
                f for f in flights_by_origin.get(hub, [])
                if f.destination == dest and f.departure_time >= f1.arrival_time + min_conn and f.departure_time <= f1.arrival_time + max_conn
            ]
            if not f2_list:
                continue
            f2 = random.choice(f2_list)
            
            # Check capacity on both legs
            if f1.available_capacity(original_class) > 0 and f2.available_capacity(original_class) > 0:
                f1.bookings[original_class] += 1
                f2.bookings[original_class] += 1
                itinerary = [f1.flight_id, f2.flight_id]
        
        if itinerary:
            pnr = f"PNR{pnr_counter}"
            pnr_counter += 1
            passengers.append(Passenger(
                pnr=pnr,
                name=name,
                pnr_type=pnr_type,
                original_class=original_class,
                itinerary=itinerary,
                special_assistance=special_assistance,
                ancillaries=ancillaries
            ))
            generated += 1
            
    return passengers


def generate_disruption(flights, passengers, flights_to_cancel=2):
    # Select flights to cancel (specifically hub-to-hub flights with high bookings)
    hub_flights = [f for f in flights if f.origin in AIRPORTS['hubs'] and f.destination in AIRPORTS['hubs'] and sum(f.bookings.values()) > 10]
    
    if len(hub_flights) < flights_to_cancel:
        # Fallback to any flight with bookings
        hub_flights = [f for f in flights if sum(f.bookings.values()) > 0]
        
    canceled_flights = random.sample(hub_flights, k=min(len(hub_flights), flights_to_cancel))
    canceled_ids = {f.flight_id for f in canceled_flights}
    
    # Find passengers who are on at least one canceled flight
    impacted_passengers = []
    for p in passengers:
        if any(fid in canceled_ids for fid in p.itinerary):
            impacted_passengers.append(p)
            
    return list(canceled_ids), impacted_passengers


if __name__ == "__main__":
    flights = generate_flight_schedule()
    passengers = generate_passengers_and_bookings(flights, 1000)
    canceled_ids, impacted = generate_disruption(flights, passengers, 2)
    print(f"Generated {len(flights)} flights, {len(passengers)} passengers.")
    print(f"Disruption canceled flights: {canceled_ids}")
    print(f"Number of impacted passengers: {len(impacted)}")
