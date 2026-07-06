import json

DEFAULT_RULE_PROFILE = {
    "passenger_priority": {
        "UM": 1000,
        "Employee": 500,
        "VIP": 800,
        "Platinum": 400,
        "Gold": 300,
        "Silver": 200,
        "Standard": 0,
        "special_assistance_bonus": 500,
        "connecting_bonus": 150
    },
    "flight_penalty": {
        "delay_weight_per_hour": 10.0,
        "connection_penalty_per_stop": 50.0,
        "downgrade_penalties": {
            "First_to_Business": 200.0,
            "First_to_Economy": 500.0,
            "Business_to_Economy": 300.0
        },
        "upgrade_incentives": {
            "Economy_to_Business": -20.0, # Negative penalty = incentive
            "Economy_to_First": -50.0,
            "Business_to_First": -30.0
        },
        "lost_ancillaries_penalty_per_service": 30.0,
        "carrier_penalties": {
            "same_carrier": 0.0,
            "partner_carrier": 50.0,
            "competitor_carrier": 200.0
        }
    },
    "rules_enabled": {
        "apply_passenger_priority": True,
        "apply_delay_penalty": True,
        "apply_connection_penalty": True,
        "apply_class_change_rules": True,
        "apply_ancillaries_rules": True,
        "apply_carrier_rules": True
    }
}

class RuleEngine:
    def __init__(self, profile=None):
        self.profile = profile or DEFAULT_RULE_PROFILE.copy()
        
    def load_profile_from_file(self, file_path):
        with open(file_path, 'r') as f:
            self.profile = json.load(f)
            
    def save_profile_to_file(self, file_path):
        with open(file_path, 'w') as f:
            json.dump(self.profile, f, indent=4)
            
    def get_passenger_priority_score(self, passenger):
        if not self.profile["rules_enabled"]["apply_passenger_priority"]:
            return 0.0
            
        p_cfg = self.profile["passenger_priority"]
        
        # Base priority by type
        score = p_cfg.get(passenger.pnr_type, 0.0)
        
        # Special assistance bonus
        if passenger.special_assistance:
            score += p_cfg.get("special_assistance_bonus", 500.0)
            
        # Connecting passenger bonus (if original itinerary had > 1 flight)
        if len(passenger.itinerary) > 1:
            score += p_cfg.get("connecting_bonus", 150.0)
            
        return float(score)
        
    def get_itinerary_penalty(self, passenger, itinerary, original_arrival, flights_dict):
        """
        Computes the penalty of assigning passenger to itinerary.
        Low penalty is preferred.
        """
        rules = self.profile["rules_enabled"]
        f_cfg = self.profile["flight_penalty"]
        
        penalty = 0.0
        
        # 1. Delay Penalty
        if rules["apply_delay_penalty"]:
            delay_td = itinerary.arrival_time - original_arrival
            delay_hours = max(0.0, delay_td.total_seconds() / 3600.0)
            penalty += delay_hours * f_cfg["delay_weight_per_hour"]
            
        # 2. Connection Penalty
        if rules["apply_connection_penalty"]:
            penalty += itinerary.stops * f_cfg["connection_penalty_per_stop"]
            
        # 3. Class Change (Upgrade / Downgrade) Penalty
        if rules["apply_class_change_rules"]:
            orig_class = passenger.original_class
            # For simplicity, we assume the passenger is offered the same class or downgraded/upgraded.
            # In our candidate itineraries, let's assume they take a class matching their original class
            # unless we downgrade them. The optimizer can choose the booking class on each flight.
            # To make things clean, let's calculate class changes if they are assigned.
            # In our router, itineraries are path-only. The specific class assigned is handled by the optimizer.
            # However, when calculating candidate cost, we can evaluate a default assignment
            # (e.g. assume they keep original class, but if they are downgraded, we add penalty).
            # We'll pass the assigned class to this function during optimization evaluation.
            pass
            
        # 4. Lost Ancillaries Penalty
        if rules["apply_ancillaries_rules"] and passenger.ancillaries:
            # If the carrier changes or the aircraft is smaller, they might lose ancillaries like Wi-Fi/Lounge.
            # Let's say if any flight is not operating on the primary carrier (AA), they lose Lounges or Wifi.
            first_flight = itinerary.flights[0]
            original_carrier = passenger.itinerary[0][:2]
            for f in itinerary.flights:
                if f.carrier != original_carrier:
                    # Lose wifi/lounge penalty
                    penalty += len(passenger.ancillaries) * f_cfg["lost_ancillaries_penalty_per_service"]
                    break
                    
        # 5. Carrier Penalty
        if rules["apply_carrier_rules"]:
            original_carrier = passenger.itinerary[0][:2]
            for f in itinerary.flights:
                if f.carrier != original_carrier:
                    if f.carrier in AIRLINE_PARTNERS.get(original_carrier, []):
                        penalty += f_cfg["carrier_penalties"]["partner_carrier"]
                    else:
                        penalty += f_cfg["carrier_penalties"]["competitor_carrier"]
                    break # apply carrier penalty once
                    
        return penalty

    def get_class_change_penalty(self, original_class, assigned_class):
        if not self.profile["rules_enabled"]["apply_class_change_rules"]:
            return 0.0
            
        if original_class == assigned_class:
            return 0.0
            
        f_cfg = self.profile["flight_penalty"]
        
        # Downgrades
        if original_class == 'First' and assigned_class == 'Business':
            return f_cfg["downgrade_penalties"]["First_to_Business"]
        if original_class == 'First' and assigned_class == 'Economy':
            return f_cfg["downgrade_penalties"]["First_to_Economy"]
        if original_class == 'Business' and assigned_class == 'Economy':
            return f_cfg["downgrade_penalties"]["Business_to_Economy"]
            
        # Upgrades
        if original_class == 'Economy' and assigned_class == 'Business':
            return f_cfg["upgrade_incentives"]["Economy_to_Business"]
        if original_class == 'Economy' and assigned_class == 'First':
            return f_cfg["upgrade_incentives"]["Economy_to_First"]
        if original_class == 'Business' and assigned_class == 'First':
            return f_cfg["upgrade_incentives"]["Business_to_First"]
            
        return 0.0

AIRLINE_PARTNERS = {
    'AA': ['UA'], # AA and UA are partners
    'UA': ['AA'],
    'DL': []      # DL is competitor to both
}
