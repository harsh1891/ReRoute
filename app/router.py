import datetime

class Itinerary:
    def __init__(self, flights):
        self.flights = flights  # list of Flight objects
        
    @property
    def flight_ids(self):
        return [f.flight_id for f in self.flights]
        
    @property
    def origin(self):
        return self.flights[0].origin if self.flights else None
        
    @property
    def destination(self):
        return self.flights[-1].destination if self.flights else None
        
    @property
    def departure_time(self):
        return self.flights[0].departure_time if self.flights else None
        
    @property
    def arrival_time(self):
        return self.flights[-1].arrival_time if self.flights else None
        
    @property
    def stops(self):
        return len(self.flights) - 1
        
    @property
    def duration(self):
        if not self.flights:
            return datetime.timedelta()
        return self.arrival_time - self.departure_time

    def to_dict(self):
        return {
            'flight_ids': self.flight_ids,
            'origin': self.origin,
            'destination': self.destination,
            'departure_time': self.departure_time.isoformat(),
            'arrival_time': self.arrival_time.isoformat(),
            'stops': self.stops,
            'duration_hours': self.duration.total_seconds() / 3600.0
        }


def find_alternative_itineraries(flights, origin, destination, earliest_departure, min_conn_mins=45, max_conn_hours=6, max_stops=1):
    """
    Finds valid alternative itineraries from origin to destination.
    Uses classical graph search (DFS/BFS traversal constraints).
    """
    candidate_itineraries = []
    flight_dict = {f.flight_id: f for f in flights}
    
    # Organize flights by origin
    flights_by_origin = {}
    for f in flights:
        flights_by_origin.setdefault(f.origin, []).append(f)
        
    min_conn = datetime.timedelta(minutes=min_conn_mins)
    max_conn = datetime.timedelta(hours=max_conn_hours)
    
    # Let's run a DFS/BFS with max depth equal to max_stops + 1
    # We want to find all paths starting at origin, ending at destination
    
    # Find direct flights (0 stops)
    direct_flights = flights_by_origin.get(origin, [])
    for f in direct_flights:
        if f.destination == destination and f.departure_time >= earliest_departure:
            candidate_itineraries.append(Itinerary([f]))
            
    # Find 1-stop flights (1 connection, 2 legs)
    if max_stops >= 1:
        leg1_candidates = flights_by_origin.get(origin, [])
        for f1 in leg1_candidates:
            if f1.departure_time < earliest_departure:
                continue
            if f1.destination == destination:
                continue # Already handled in direct
                
            # Intermediary hub or spoke
            transit = f1.destination
            leg2_candidates = flights_by_origin.get(transit, [])
            for f2 in leg2_candidates:
                if f2.destination == destination:
                    # Check connection timing constraint
                    if f2.departure_time >= f1.arrival_time + min_conn and f2.departure_time <= f1.arrival_time + max_conn:
                        candidate_itineraries.append(Itinerary([f1, f2]))
                        
    # Find 2-stop flights (2 connections, 3 legs)
    if max_stops >= 2:
        leg1_candidates = flights_by_origin.get(origin, [])
        for f1 in leg1_candidates:
            if f1.departure_time < earliest_departure:
                continue
            if f1.destination == destination:
                continue
                
            transit1 = f1.destination
            leg2_candidates = flights_by_origin.get(transit1, [])
            for f2 in leg2_candidates:
                if f2.destination == destination or f2.destination == origin:
                    continue
                if not (f2.departure_time >= f1.arrival_time + min_conn and f2.departure_time <= f1.arrival_time + max_conn):
                    continue
                    
                transit2 = f2.destination
                leg3_candidates = flights_by_origin.get(transit2, [])
                for f3 in leg3_candidates:
                    if f3.destination == destination:
                        if f3.departure_time >= f2.arrival_time + min_conn and f3.departure_time <= f2.arrival_time + max_conn:
                            candidate_itineraries.append(Itinerary([f1, f2, f3]))
                            
    return candidate_itineraries


def get_passenger_disrupted_origin_and_time(passenger, canceled_flight_ids, flights_dict):
    """
    Analyzes passenger's original itinerary and finds where they get stranded.
    Returns: (stranded_airport, earliest_departure_time)
    """
    first_canceled_index = -1
    for i, fid in enumerate(passenger.itinerary):
        if fid in canceled_flight_ids:
            first_canceled_index = i
            break
            
    if first_canceled_index == -1:
        # Not actually disrupted
        return None, None
        
    canceled_flight_id = passenger.itinerary[first_canceled_index]
    canceled_flight = flights_dict[canceled_flight_id]
    
    # The stranded airport is the origin of the canceled flight
    stranded_airport = canceled_flight.origin
    
    # Earliest departure is the scheduled departure of that canceled flight
    earliest_departure = canceled_flight.departure_time
    
    return stranded_airport, earliest_departure


def get_candidate_itineraries_for_passenger(passenger, flights, canceled_flight_ids, K=3):
    """
    Finds the top K candidate alternative itineraries for an impacted passenger.
    Ranks them heuristically (shorter delay, fewer stops, same carrier preference) to pick top K.
    """
    flights_dict = {f.flight_id: f for f in flights}
    
    stranded_airport, earliest_departure = get_passenger_disrupted_origin_and_time(
        passenger, canceled_flight_ids, flights_dict
    )
    
    if not stranded_airport:
        return []
        
    # Get original itinerary destination
    final_destination = flights_dict[passenger.itinerary[-1]].destination
    original_arrival = flights_dict[passenger.itinerary[-1]].arrival_time
    
    # Search candidates
    raw_candidates = find_alternative_itineraries(
        flights, stranded_airport, final_destination, earliest_departure, max_stops=1
    )
    
    # If no candidates, try with 2 stops
    if not raw_candidates:
        raw_candidates = find_alternative_itineraries(
            flights, stranded_airport, final_destination, earliest_departure, max_stops=2
        )
        
    # Rank candidates heuristically to keep top K
    # Heuristic scoring (lower score is better):
    # - Delay (hours) * 10
    # - Stops * 50
    # - Partner carrier (+20), Competitor carrier (+100)
    scored_candidates = []
    for itin in raw_candidates:
        delay = (itin.arrival_time - original_arrival).total_seconds() / 3600.0
        # If arrive earlier or minimal delay, that's good. Avoid negative delay if flights depart earlier.
        delay_penalty = max(0.0, delay) * 10.0
        
        stops_penalty = itin.stops * 50.0
        
        carrier_penalty = 0.0
        # If any flight in itin is not the same carrier as passenger's original carrier
        original_carrier = passenger.itinerary[0][:2] # e.g. 'AA'
        for f in itin.flights:
            if f.carrier != original_carrier:
                if f.carrier in ['UA', 'DL']: # other carriers
                    carrier_penalty += 50.0
                    
        total_score = delay_penalty + stops_penalty + carrier_penalty
        scored_candidates.append((total_score, itin))
        
    # Sort and take top K
    scored_candidates.sort(key=lambda x: x[0])
    top_candidates = [itin for score, itin in scored_candidates[:K]]
    
    return top_candidates
