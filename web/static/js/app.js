// Geocoordinates for Airports on the 1000x500 SVG Canvas
const AIRPORT_COORDS = {
    // Hubs
    'ORD': { x: 550, y: 160 },
    'DFW': { x: 480, y: 380 },
    'DEN': { x: 340, y: 220 },
    'JFK': { x: 860, y: 140 },
    'LAX': { x: 100, y: 320 },
    // Spokes
    'SEA': { x: 100, y: 60 },
    'SFO': { x: 60, y: 200 },
    'MIA': { x: 820, y: 440 },
    'BOS': { x: 920, y: 100 },
    'LAS': { x: 180, y: 280 },
    'PHX': { x: 200, y: 360 },
    'CLT': { x: 740, y: 260 },
    'MSP': { x: 500, y: 100 },
    'DTW': { x: 680, y: 150 },
    'IAH': { x: 520, y: 430 }
};

// Default Rule Profile matching the backend structures
let currentRuleProfile = {
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
            "Economy_to_Business": -20.0,
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
        "apply_passenger_priority": true,
        "apply_delay_penalty": true,
        "apply_connection_penalty": true,
        "apply_class_change_rules": true,
        "apply_ancillaries_rules": true,
        "apply_carrier_rules": true
    }
};

// State Variables
let flightSchedule = [];
let canceledFlightIds = [];
let impactedPassengers = [];
let solutionsData = null;
let benchmarkChart = null;

// ==========================================================================
// Initialization
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    initTabRouting();
    initRuleSliders();
    initButtons();
    loadScheduleData();
    loadBenchmarkResults();
});

// Tab Navigation
function initTabRouting() {
    const navItems = document.querySelectorAll(".nav-item");
    const tabContents = document.querySelectorAll(".tab-content");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            
            navItems.forEach(nav => nav.classList.remove("active"));
            tabContents.forEach(tab => tab.classList.remove("active"));
            
            item.classList.add("active");
            document.getElementById(targetTab).classList.add("active");

            // Chart needs to be re-rendered/resized if benchmark tab becomes active
            if (targetTab === 'benchmark-tab' && benchmarkChart) {
                benchmarkChart.resize();
            }
        });
    });

    // Solutions internal tabs
    const solTabs = document.querySelectorAll(".sol-tab");
    const solContents = document.querySelectorAll(".sol-content");

    solTabs.forEach(item => {
        item.addEventListener("click", () => {
            const targetSol = item.getAttribute("data-sol");
            
            solTabs.forEach(t => t.classList.remove("active"));
            solContents.forEach(c => c.classList.remove("active"));
            
            item.classList.add("active");
            document.getElementById(targetSol).classList.add("active");
        });
    });
}

// Bind UI sliders and toggles to rule profile state
function initRuleSliders() {
    // Passenger Priority
    setupSlider("weight-um", "val-um", (val) => currentRuleProfile.passenger_priority.UM = parseInt(val));
    setupSlider("weight-assistance", "val-assistance", (val) => currentRuleProfile.passenger_priority.special_assistance_bonus = parseInt(val));
    setupSlider("weight-employee", "val-employee", (val) => currentRuleProfile.passenger_priority.Employee = parseInt(val));
    setupSlider("weight-plat", "val-plat", (val) => currentRuleProfile.passenger_priority.VIP = parseInt(val));
    setupSlider("weight-gold", "val-gold", (val) => currentRuleProfile.passenger_priority.Gold = parseInt(val));
    setupSlider("weight-silver", "val-silver", (val) => currentRuleProfile.passenger_priority.Silver = parseInt(val));

    // Flight Penalties
    setupSlider("weight-delay", "val-delay", (val) => currentRuleProfile.flight_penalty.delay_weight_per_hour = parseFloat(val), " pts/hr");
    setupSlider("weight-connection", "val-connection", (val) => currentRuleProfile.flight_penalty.connection_penalty_per_stop = parseFloat(val), " pts");
    setupSlider("weight-ancillaries", "val-ancillaries", (val) => currentRuleProfile.flight_penalty.lost_ancillaries_penalty_per_service = parseFloat(val), " pts");

    // Upgrade/Downgrade & Carrier
    setupSlider("weight-f-to-b", "val-f-to-b", (val) => currentRuleProfile.flight_penalty.downgrade_penalties.First_to_Business = parseFloat(val));
    setupSlider("weight-b-to-e", "val-b-to-e", (val) => currentRuleProfile.flight_penalty.downgrade_penalties.Business_to_Economy = parseFloat(val));
    setupSlider("weight-competitor", "val-competitor", (val) => currentRuleProfile.flight_penalty.carrier_penalties.competitor_carrier = parseFloat(val), " pts");
    setupSlider("weight-partner", "val-partner", (val) => currentRuleProfile.flight_penalty.carrier_penalties.partner_carrier = parseFloat(val));

    // Toggles
    setupToggle("rule-enable-priority", (checked) => currentRuleProfile.rules_enabled.apply_passenger_priority = checked);
    setupToggle("rule-enable-delay", (checked) => currentRuleProfile.rules_enabled.apply_delay_penalty = checked);
    setupToggle("rule-enable-connection", (checked) => currentRuleProfile.rules_enabled.apply_connection_penalty = checked);
    setupToggle("rule-enable-class", (checked) => currentRuleProfile.rules_enabled.apply_class_change_rules = checked);
    setupToggle("rule-enable-ancillaries", (checked) => currentRuleProfile.rules_enabled.apply_ancillaries_rules = checked);
    setupToggle("rule-enable-carrier", (checked) => currentRuleProfile.rules_enabled.apply_carrier_rules = checked);

    // Initialize values from default rules
    loadDefaultSliderValues();
}

function setupSlider(sliderId, valId, callback, suffix = " pts") {
    const slider = document.getElementById(sliderId);
    const label = document.getElementById(valId);
    
    slider.addEventListener("input", (e) => {
        const val = e.target.value;
        label.textContent = val + suffix;
        callback(val);
    });
}

function setupToggle(toggleId, callback) {
    const toggle = document.getElementById(toggleId);
    toggle.addEventListener("change", (e) => {
        callback(e.target.checked);
    });
}

function loadDefaultSliderValues() {
    // Passenger Priority
    setSliderVal("weight-um", "val-um", currentRuleProfile.passenger_priority.UM);
    setSliderVal("weight-assistance", "val-assistance", currentRuleProfile.passenger_priority.special_assistance_bonus);
    setSliderVal("weight-employee", "val-employee", currentRuleProfile.passenger_priority.Employee);
    setSliderVal("weight-plat", "val-plat", currentRuleProfile.passenger_priority.VIP);
    setSliderVal("weight-gold", "val-gold", currentRuleProfile.passenger_priority.Gold);
    setSliderVal("weight-silver", "val-silver", currentRuleProfile.passenger_priority.Silver);

    // Flight Penalties
    setSliderVal("weight-delay", "val-delay", currentRuleProfile.flight_penalty.delay_weight_per_hour, " pts/hr");
    setSliderVal("weight-connection", "val-connection", currentRuleProfile.flight_penalty.connection_penalty_per_stop, " pts");
    setSliderVal("weight-ancillaries", "val-ancillaries", currentRuleProfile.flight_penalty.lost_ancillaries_penalty_per_service, " pts");

    // Upgrade/Downgrade & Carrier
    setSliderVal("weight-f-to-b", "val-f-to-b", currentRuleProfile.flight_penalty.downgrade_penalties.First_to_Business);
    setSliderVal("weight-b-to-e", "val-b-to-e", currentRuleProfile.flight_penalty.downgrade_penalties.Business_to_Economy);
    setSliderVal("weight-competitor", "val-competitor", currentRuleProfile.flight_penalty.carrier_penalties.competitor_carrier, " pts");
    setSliderVal("weight-partner", "val-partner", currentRuleProfile.flight_penalty.carrier_penalties.partner_carrier);
}

function setSliderVal(sliderId, valId, value, suffix = " pts") {
    const slider = document.getElementById(sliderId);
    const label = document.getElementById(valId);
    slider.value = value;
    label.textContent = value + suffix;
}

// Bind Action Buttons
function initButtons() {
    document.getElementById("run-optimization-btn").addEventListener("click", runOptimization);
    document.getElementById("trigger-benchmark-btn").addEventListener("click", runBenchmarkSuite);
    
    // Exception Search & Filter
    document.getElementById("pnr-search").addEventListener("input", filterExceptionsTable);
    document.getElementById("filter-priority").addEventListener("change", filterExceptionsTable);
    document.getElementById("filter-reason").addEventListener("change", filterExceptionsTable);
}

// ==========================================================================
// API Loaders & Action Handlers
// ==========================================================================

// Load flight schedule network on load
async function loadScheduleData() {
    try {
        const response = await fetch('/api/schedule');
        const data = await response.json();
        
        flightSchedule = data.flights;
        canceledFlightIds = data.canceled_flight_ids;
        impactedPassengers = data.impacted_passengers;

        document.getElementById("stat-impacted").textContent = data.impacted_passengers_count;
        
        // Render network map
        drawFlightNetworkMap();
        populateCanceledFlightsList();
    } catch (err) {
        console.error("Error loading schedule data:", err);
    }
}

// Draw Geographically Routed Flight Network Map
function drawFlightNetworkMap() {
    const svg = document.getElementById("flight-network-svg");
    svg.innerHTML = ''; // Clear SVG
    
    // Re-add marker definitions (cleared by innerHTML = '')
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `
        <marker id="arrow" viewBox="0 0 10 10" refX="25" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#38bdf8" opacity="0.4"/>
        </marker>
        <marker id="arrow-canceled" viewBox="0 0 10 10" refX="25" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444" opacity="0.8"/>
        </marker>
        <marker id="arrow-reroute" viewBox="0 0 10 10" refX="25" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#c084fc" opacity="0.9"/>
        </marker>
    `;
    svg.appendChild(defs);

    // 1. Draw flight paths (edges)
    // To avoid rendering duplicate paths for flights sharing the same endpoints, we group by endpoints
    const edgesGroup = {};
    flightSchedule.forEach(f => {
        const key = [f.origin, f.destination].sort().join('-');
        edgesGroup[key] = edgesGroup[key] || [];
        edgesGroup[key].push(f);
    });

    Object.values(edgesGroup).forEach(flights => {
        flights.forEach((f, idx) => {
            const p1 = AIRPORT_COORDS[f.origin];
            const p2 = AIRPORT_COORDS[f.destination];
            if (!p1 || !p2) return;

            const isCanceled = canceledFlightIds.includes(f.flight_id);
            const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
            
            // Calculate a curve offset if there are multiple flights between same cities
            const midX = (p1.x + p2.x) / 2;
            const midY = (p1.y + p2.y) / 2;
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const len = Math.sqrt(dx*dx + dy*dy);
            
            // Curve equation (quadratic bezier control point)
            let cx = midX;
            let cy = midY;
            
            if (flights.length > 1) {
                const perpX = -dy / len;
                const perpY = dx / len;
                const offset = (idx - (flights.length - 1) / 2) * 20; // curve separation
                cx = midX + perpX * offset;
                cy = midY + perpY * offset;
            }

            const pathD = `M ${p1.x} ${p1.y} Q ${cx} ${cy} ${p2.x} ${p2.y}`;
            path.setAttribute("d", pathD);
            path.setAttribute("id", `edge-${f.flight_id}`);
            
            if (isCanceled) {
                path.setAttribute("stroke", "#ef4444");
                path.setAttribute("stroke-width", "2");
                path.setAttribute("opacity", "0.95");
                path.setAttribute("class", "flight-edge canceled");
                path.setAttribute("marker-end", "url(#arrow-canceled)");
            } else {
                path.setAttribute("stroke", "#38bdf8");
                path.setAttribute("stroke-width", "1");
                path.setAttribute("opacity", "0.22");
                path.setAttribute("class", "flight-edge");
                path.setAttribute("marker-end", "url(#arrow)");
            }
            path.setAttribute("fill", "none");

            // Hover tooltip on edges
            const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
            title.textContent = `${f.flight_id}: ${f.origin} -> ${f.destination}\nDep: ${f.departure_time}\nArr: ${f.arrival_time}\nCarrier: ${f.carrier}\nBookings: ${f.bookings_eco+f.bookings_biz+f.bookings_first} seats`;
            path.appendChild(title);

            svg.appendChild(path);
        });
    });

    // 2. Draw airports (nodes)
    Object.entries(AIRPORT_COORDS).forEach(([ap, coord]) => {
        const isHub = ['ORD', 'DFW', 'DEN', 'JFK', 'LAX'].includes(ap);
        
        const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        
        circle.setAttribute("cx", coord.x);
        circle.setAttribute("cy", coord.y);
        circle.setAttribute("class", "node-circle");
        
        if (isHub) {
            circle.setAttribute("r", "7");
            circle.setAttribute("fill", "#38bdf8");
            circle.setAttribute("stroke", "rgba(56, 189, 248, 0.4)");
            circle.setAttribute("stroke-width", "4");
            circle.setAttribute("style", "filter: drop-shadow(0 0 4px var(--color-primary-glow));");
        } else {
            circle.setAttribute("r", "5");
            circle.setAttribute("fill", "#64748b");
            circle.setAttribute("stroke", "rgba(255,255,255,0.05)");
            circle.setAttribute("stroke-width", "1");
        }
        
        const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
        text.setAttribute("x", coord.x + 10);
        text.setAttribute("y", coord.y + 4);
        text.setAttribute("class", "node-label");
        text.textContent = ap;
        
        group.appendChild(circle);
        group.appendChild(text);
        
        const nodeTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
        nodeTitle.textContent = `${ap} - ${isHub ? 'Hub Airport' : 'Spoke Airport'}`;
        group.appendChild(nodeTitle);

        svg.appendChild(group);
    });
}

function populateCanceledFlightsList() {
    const listDiv = document.getElementById("canceled-flights-list");
    listDiv.innerHTML = '';

    canceledFlightIds.forEach(fid => {
        const f = flightSchedule.find(flight => flight.flight_id === fid);
        if (!f) return;

        const totalBooked = f.bookings_first + f.bookings_biz + f.bookings_eco;
        const item = document.createElement("div");
        item.className = "disruption-item";
        item.innerHTML = `
            <div class="disruption-details">
                <span class="disruption-flight">${f.flight_id} Canceled</span>
                <span class="disruption-path">${f.origin} <i class="fa-solid fa-arrow-right"></i> ${f.destination}</span>
            </div>
            <div class="disruption-passengers text-error">
                <i class="fa-solid fa-users"></i> ${totalBooked} booked
            </div>
        `;
        listDiv.appendChild(item);
    });
}

// Run Optimization via API
async function runOptimization() {
    const solverType = document.getElementById("solver-select").value;
    const btn = document.getElementById("run-optimization-btn");
    const statusBadge = document.getElementById("solving-status");
    
    // UI state loading
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Optimizing...`;
    statusBadge.textContent = "Optimizing";
    statusBadge.className = "badge badge-inactive pulse-green";
    
    try {
        const response = await fetch('/api/optimize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                solver_type: solverType,
                rule_profile: currentRuleProfile
            })
        });
        
        const data = await response.json();
        solutionsData = data;
        
        // Update stats
        document.getElementById("stat-accommodated").textContent = data.stats.accommodated;
        document.getElementById("stat-exceptions").textContent = data.stats.exceptions;
        document.getElementById("stat-success").textContent = `${data.stats.success_rate.toFixed(1)}%`;
        
        document.getElementById("solving-status").textContent = data.solver_status;
        document.getElementById("solving-status").className = "badge badge-success";
        document.getElementById("solving-time").textContent = `${data.solve_time_seconds.toFixed(3)}s`;

        // Render solutions
        populateDefaultMappingsTable(data.default_flight_solution);
        populateExceptionsTable(data.exceptions);

        // Reset map highlights & Draw re-routed passenger paths on hover
        drawFlightNetworkMap();

    } catch (err) {
        console.error("Error running optimization:", err);
        statusBadge.textContent = "Error";
        statusBadge.className = "badge badge-error";
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-bolt"></i> Run Optimizer`;
    }
}

function populateDefaultMappingsTable(defaultMappings) {
    const tbody = document.getElementById("default-mappings-table");
    tbody.innerHTML = '';

    if (Object.keys(defaultMappings).length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-center py-8">No default flight mappings generated</td></tr>`;
        return;
    }

    Object.entries(defaultMappings).forEach(([canceledFid, mapping]) => {
        const origFlight = flightSchedule.find(f => f.flight_id === canceledFid);
        const altFlight = flightSchedule.find(f => f.flight_id === mapping.alternate_flight_id);
        if (!origFlight || !altFlight) return;

        const row = document.createElement("tr");
        row.innerHTML = `
            <td><strong class="text-error">${canceledFid}</strong></td>
            <td><strong class="text-success">${mapping.alternate_flight_id}</strong></td>
            <td>${origFlight.origin} <i class="fa-solid fa-arrow-right"></i> ${origFlight.destination}</td>
            <td>${mapping.passengers_count} passengers</td>
            <td><span class="badge badge-success">Mapped</span></td>
        `;

        // Add map highlights on hover
        row.addEventListener("mouseenter", () => highlightFlightPathOnMap([canceledFid, mapping.alternate_flight_id]));
        row.addEventListener("mouseleave", () => resetFlightNetworkHighlights());

        tbody.appendChild(row);
    });
}

function populateExceptionsTable(exceptions) {
    const tbody = document.getElementById("exceptions-table-body");
    tbody.innerHTML = '';

    if (exceptions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center py-8">No exceptions to report</td></tr>`;
        return;
    }

    exceptions.forEach(exc => {
        const details = exc.details;
        const priorityBadgeClass = getPriorityBadgeClass(details.pnr_type);
        
        let itinDisplay = details.assigned_itinerary.length > 0 
            ? details.assigned_itinerary.map(fid => `<span class="badge badge-success">${fid}</span>`).join(' ') 
            : '<span class="badge badge-error">Unaccommodated</span>';

        const row = document.createElement("tr");
        row.className = "exception-row";
        row.setAttribute("data-pnr", exc.pnr);
        row.setAttribute("data-pnr-type", details.pnr_type);
        row.setAttribute("data-reason", details.assigned_itinerary.length > 0 ? "route" : "capacity");

        row.innerHTML = `
            <td><strong>${exc.pnr}</strong></td>
            <td>${details.name}</td>
            <td><span class="badge ${priorityBadgeClass}">${details.pnr_type}</span></td>
            <td><strong class="text-error">${details.canceled_flight}</strong></td>
            <td>${itinDisplay}</td>
            <td class="text-secondary">${exc.reason}</td>
        `;

        // Highlight passenger re-routed path on hover (if accommodated)
        if (details.assigned_itinerary.length > 0) {
            row.addEventListener("mouseenter", () => highlightFlightPathOnMap(details.assigned_itinerary));
            row.addEventListener("mouseleave", () => resetFlightNetworkHighlights());
        }

        tbody.appendChild(row);
    });
}

function getPriorityBadgeClass(pnrType) {
    switch (pnrType) {
        case 'UM': return 'badge-error';
        case 'VIP':
        case 'Platinum': return 'badge-yellow';
        case 'Gold':
        case 'Silver': return 'badge-success';
        case 'Employee': return 'bg-purple';
        default: return 'badge-inactive';
    }
}

// Map path highlights on hover
function highlightFlightPathOnMap(flightIds) {
    // Dim all lines first
    document.querySelectorAll(".flight-edge").forEach(edge => {
        edge.setAttribute("opacity", "0.05");
    });

    // Highlight the specific flights
    flightIds.forEach(fid => {
        const edge = document.getElementById(`edge-${fid}`);
        if (edge) {
            edge.setAttribute("opacity", "0.95");
            edge.setAttribute("stroke-width", "3.5");
            edge.setAttribute("stroke", "#c084fc"); // Purple highlight for re-routed
            edge.setAttribute("marker-end", "url(#arrow-reroute)");
        }
    });
}

function resetFlightNetworkHighlights() {
    document.querySelectorAll(".flight-edge").forEach(edge => {
        const fid = edge.getAttribute("id").replace("edge-", "");
        const isCanceled = canceledFlightIds.includes(fid);
        if (isCanceled) {
            edge.setAttribute("stroke", "#ef4444");
            edge.setAttribute("stroke-width", "2");
            edge.setAttribute("opacity", "0.95");
            edge.setAttribute("marker-end", "url(#arrow-canceled)");
        } else {
            edge.setAttribute("stroke", "#38bdf8");
            edge.setAttribute("stroke-width", "1");
            edge.setAttribute("opacity", "0.22");
            edge.setAttribute("marker-end", "url(#arrow)");
        }
    });
}

// Local filtering for exceptions list
function filterExceptionsTable() {
    const query = document.getElementById("pnr-search").value.toLowerCase();
    const priorityFilter = document.getElementById("filter-priority").value;
    const reasonFilter = document.getElementById("filter-reason").value;

    const rows = document.querySelectorAll("#exceptions-table-body tr.exception-row");
    
    rows.forEach(row => {
        const pnr = row.cells[0].textContent.toLowerCase();
        const name = row.cells[1].textContent.toLowerCase();
        const pnrType = row.getAttribute("data-pnr-type");
        const reason = row.getAttribute("data-reason"); // 'route' or 'capacity'

        const matchesQuery = pnr.includes(query) || name.includes(query);
        
        let matchesPriority = true;
        if (priorityFilter) {
            if (priorityFilter === 'VIP') {
                matchesPriority = ['VIP', 'Platinum'].includes(pnrType);
            } else {
                matchesPriority = pnrType === priorityFilter;
            }
        }

        const matchesReason = !reasonFilter || reason === reasonFilter;

        if (matchesQuery && matchesPriority && matchesReason) {
            row.style.display = "";
        } else {
            row.style.display = "none";
        }
    });
}

// ==========================================================================
// Benchmarking & Charting
// ==========================================================================

async function runBenchmarkSuite() {
    const btn = document.getElementById("trigger-benchmark-btn");
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> Benchmarking...`;

    try {
        const response = await fetch('/api/benchmark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ scales: [10, 50, 100, 200, 500] }) // Scale benchmark up to 500
        });
        const data = await response.json();
        renderBenchmarkChart(data);
        populateBenchmarkAnalysis(data);
    } catch (err) {
        console.error("Error running benchmark suite:", err);
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-play"></i> Run Benchmarking Suite`;
    }
}

async function loadBenchmarkResults() {
    try {
        const response = await fetch('/api/benchmark-results');
        const data = await response.json();
        renderBenchmarkChart(data);
        populateBenchmarkAnalysis(data);
    } catch (err) {
        console.error("Error loading benchmark results:", err);
    }
}

function renderBenchmarkChart(data) {
    const ctx = document.getElementById('benchmark-chart').getContext('2d');
    
    // Destroy previous chart
    if (benchmarkChart) {
        benchmarkChart.destroy();
    }

    const scales = data.scales;
    const baselineTimes = [];
    const milpTimes = [];
    const cqmTimes = [];

    scales.forEach(s => {
        const res = data.results[s];
        if (res && res.solvers) {
            baselineTimes.push(res.solvers.baseline ? res.solvers.baseline.solve_time : null);
            milpTimes.push(res.solvers.milp ? res.solvers.milp.solve_time : null);
            cqmTimes.push(res.solvers.cqm ? res.solvers.cqm.solve_time : null);
        }
    });

    // Chart configs
    benchmarkChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: scales.map(s => `${s} Passengers`),
            datasets: [
                {
                    label: 'Unconstrained Classical MILP (Baseline)',
                    data: baselineTimes,
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    borderWidth: 2.5,
                    pointBackgroundColor: '#ef4444',
                    tension: 0.15,
                    spanGaps: true
                },
                {
                    label: 'Graph-Constrained Classical MILP',
                    data: milpTimes,
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    borderWidth: 2.5,
                    pointBackgroundColor: '#38bdf8',
                    tension: 0.15
                },
                {
                    label: 'Graph-Constrained Hybrid Quantum CQM',
                    data: cqmTimes,
                    borderColor: '#a855f7',
                    backgroundColor: 'rgba(168, 85, 247, 0.1)',
                    borderWidth: 2.5,
                    pointBackgroundColor: '#a855f7',
                    tension: 0.15
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                legend: {
                    labels: { color: '#94a3b8', font: { family: 'Inter', size: 12 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 22, 42, 0.95)',
                    titleColor: '#f8fafc',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    borderWidth: 1,
                    padding: 10,
                    titleFont: { family: 'Outfit', weight: 'bold' },
                    bodyFont: { family: 'Inter' }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: { color: '#94a3b8', font: { family: 'Inter' } }
                },
                y: {
                    type: 'logarithmic',
                    title: {
                        display: true,
                        text: 'Execution Time (Seconds) [Log Scale]',
                        color: '#94a3b8',
                        font: { family: 'Outfit', size: 13 }
                    },
                    grid: { color: 'rgba(255,255,255,0.03)' },
                    ticks: {
                        color: '#94a3b8',
                        font: { family: 'Inter' },
                        callback: function(value, index, values) {
                            return value + 's';
                        }
                    }
                }
            }
        }
    });
}

function populateBenchmarkAnalysis(data) {
    const container = document.getElementById("benchmark-analysis-text");
    const breakdown = data.complexity_breakdown;
    
    // Find the speedup at the maximum scale where baseline solved (e.g. scale 100 or 200)
    let maxScaleWithBaseline = 10;
    let maxSpeedup = 1.0;
    
    data.scales.forEach(s => {
        const res = data.results[s];
        if (res && res.solvers && res.solvers.baseline && res.solvers.baseline.status === 'Optimal') {
            maxScaleWithBaseline = s;
            maxSpeedup = res.speedup_milp || 1.0;
        }
    });

    // Check if any scales timed out
    let timeoutReport = "";
    data.scales.forEach(s => {
        const res = data.results[s];
        if (res && res.solvers && res.solvers.baseline && res.solvers.baseline.status === 'Timeout') {
            timeoutReport += `<li>Baseline <strong>timed out (exceeded 30s)</strong> at N=${s} passengers, while the Graph-Constrained MILP solved in <strong>${res.solvers.milp.solve_time.toFixed(4)}s</strong>.</li>`;
        }
    });
    
    if (timeoutReport) {
        timeoutReport = `<ul class="disruption-list mt-3 pl-4" style="list-style-type: disc;">${timeoutReport}</ul>`;
    }

    container.innerHTML = `
        <div class="benchmark-summary card-inner-glass">
            <h4>Observations & Results</h4>
            <p class="text-secondary mt-1">At scale N = ${maxScaleWithBaseline} passengers, the unconstrained baseline solver took <strong>${data.results[maxScaleWithBaseline].solvers.baseline.solve_time.toFixed(3)}s</strong>, whereas the graph-filtered optimizer completed in <strong>${data.results[maxScaleWithBaseline].solvers.milp.solve_time.toFixed(4)}s</strong>, yielding a measured speedup of <strong>${maxSpeedup.toFixed(1)}x</strong>.</p>
            ${timeoutReport}
        </div>
        
        <div class="complexity-box">
            <h4>Complexity Breakdown</h4>
            <div class="complexity-grid">
                <div class="complexity-card">
                    <h5>Variables Reduction</h5>
                    <p>Unconstrained: <strong>${breakdown.variables_comparison.unconstrained}</strong></p>
                    <p class="mt-2 text-success">Constrained: <strong>${breakdown.variables_comparison.constrained}</strong></p>
                </div>
                <div class="complexity-card">
                    <h5>Constraints Simplification</h5>
                    <p>Unconstrained: <strong>${breakdown.constraints_comparison.unconstrained}</strong></p>
                    <p class="mt-2 text-success">Constrained: <strong>${breakdown.constraints_comparison.constrained}</strong></p>
                </div>
            </div>
            <p class="text-secondary text-sm mt-3"><i class="fa-solid fa-gears"></i> <strong>Solver Implications:</strong> ${breakdown.solver_complexity}</p>
        </div>
    `;
}
