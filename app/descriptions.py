"""What each single-value patch table does, shown in the table editor's list view. Factory tables have no descriptions in
the NC Flash definitions, so they get one built from the definition (category, units, range); any description can be
replaced by the user's own text (double-click it; saved in settings.json)."""

PATCH = {
    # ignition cut, launch control, flat-foot shift
    'RPM Ignition Cut - Enable (custom patch)': 'Turns the ignition-cut rev limiter on (1) or off (0). Launch control and flat shift use the same cut.',
    'RPM Ignition Cut - Offset from RPM Fuel Cut (custom patch)': 'Where the spark cut starts, relative to the factory RPM Fuel Cut table (negative = below it). Change the rev limit itself in RPM Fuel Cut.',
    'RPM Ignition Cut - Coil Dwell While Cutting (custom patch)': 'Coil charge time while cutting. Shorter = weaker spark = harder cut and more pops. Never below 0.2 ms.',
    'RPM Ignition Cut - Timing Retard While Cutting (custom patch)': 'Degrees of timing taken away while the cut is active. More retard = more heat into the exhaust.',
    'RPM Ignition Cut - Launch Control RPM, clutch in and stopped (custom patch)': 'Revs held by the ignition cut with the clutch down and the car stopped (below the split speed). 0 = launch control off.',
    'RPM Ignition Cut - Flat Shift RPM, clutch in and moving at full pedal (custom patch)': 'Revs held with the clutch down while moving and the pedal above the flat-shift minimum, for flat-foot shifts. 0 = off.',
    'RPM Ignition Cut - Launch / Flat Shift Split Speed (custom patch)': 'Below this speed the clutch-down limit is launch control; above it, flat shift.',
    'RPM Ignition Cut - Flat Shift Minimum Pedal (custom patch)': 'Flat shift only acts with the pedal above this, so a normal clutch-in coast isn\'t cut.',
    'Overheat Rev Limit - Enable (custom patch)': 'Lowers the rev limit (and launch / flat-shift points) when the coolant gets too hot. 1 = on.',
    'Overheat Rev Limit - Start Temp, limit begins above this (custom patch)': 'Coolant temperature where the rev limit starts coming down.',
    'Overheat Rev Limit - Full Temp, Limited RPM at and above this (custom patch)': 'Coolant temperature where the rev limit reaches the Limited RPM.',
    'Overheat Rev Limit - Limited RPM, min 3000 (custom patch)': 'Rev limit at and above the full temperature. Never below 3000 rpm.',
    # rev-match, upshift hold, anti-stall
    'Rev Match - Enable (custom patch)': 'Turns downshift rev-match on (1) or off (0). Clutch + brake: the throttle blips to the next gear down\'s revs.',
    'Rev Match - Max Output Pedal % (custom patch)': 'Most throttle rev-match or upshift hold may open (pedal %). The code never goes above 40%.',
    'Rev Match - Max Real Pedal % to Allow (custom patch)': 'Rev-match only acts with your foot (almost) off the pedal: real pedal at or below this.',
    'Rev Match - Min Speed (custom patch)': 'No rev-match below this speed.',
    'Rev Match - Brake Switch RAM Address [hex] (custom patch)': 'Where the ECU keeps the brake switch (found by NC Patcher\'s car check). Only change it for your car\'s confirmed address.',
    'Rev Match - Max Hold Time, calls ~5.5 ms (custom patch)': 'Longest a blip / hold may last per clutch press (calls of ~5.5 ms; 270 = 1.5 s). Capped at 600 in code.',
    'Rev Match - Clutch Hold Delay before it acts, ms (custom patch)': 'How long the clutch must stay down before the throttle opens. Raise it if the car jolts as you press the clutch; 0 = no delay.',
    'Rev Match - Gain, % pedal per rpm error (custom patch)': 'How hard it opens the throttle per rpm below the target. Higher = faster, but can overshoot.',
    'Rev Match - Damping, % per rpm change per call (custom patch)': 'Takes throttle away as the revs rise quickly, to stop overshoot. Raise it if the revs flare past the target.',
    'Rev Match - Target Offset rpm (custom patch)': 'Extra revs added to the downshift target (positive = blip slightly above the matched rpm).',
    'Rev Match - On/Off Switch Enable, stopped + clutch down + 3 brake taps (custom patch)': 'Lets you turn downshift rev-match on or off without a laptop: stopped, clutch down, tap the brake 3 times.',
    'Rev Match - On/Off Switch State at Start-up, 1 = on (custom patch)': 'Whether downshift rev-match starts on (1) or off (0) at every key-on.',
    'Rev Match - On/Off Switch Tap Window (custom patch)': 'Time allowed for the 3 brake taps (calls of ~5.5 ms; 364 = 2 s).',
    'Rev Match - On/Off Switch Confirm RPM, switched on (custom patch)': 'Revs briefly held to confirm the switch turned rev-match on.',
    'Rev Match - On/Off Switch Confirm RPM, switched off (custom patch)': 'Revs briefly held to confirm the switch turned rev-match off.',
    'Rev Match - On/Off Switch Confirm Time, 0 = none (custom patch)': 'How long the confirmation revs are held (calls of ~5.5 ms). 0 = no confirmation.',
    'Rev Match - Max Target RPM (custom patch)': 'Rev-match and upshift hold never aim above this rpm.',
    'Rev Match - Upshift Hold Enable, no brake (custom patch)': 'Turns upshift hold on (1): clutch down without the brake holds the next gear up\'s revs so they don\'t drop too far.',
    'Rev Match - Upshift Target Offset rpm (custom patch)': 'Extra revs added to the upshift hold target.',
    'Anti-Stall - Enable (custom patch)': 'Adds a little throttle if the revs dip at low speed, to help stop stalls. 1 = on.',
    'Anti-Stall - RPM (keep below idle target) (custom patch)': 'Anti-stall acts below this rpm. Keep it below the idle target so it doesn\'t fight the idle control.',
    'Anti-Stall - Gain, % pedal per rpm below (custom patch)': 'Throttle added per rpm below the anti-stall RPM.',
    'Anti-Stall - Max Pedal % (limit 20) (custom patch)': 'Most throttle anti-stall may add. Never above 20% in code.',
    'Anti-Stall - Max Speed km/h (custom patch)': 'Anti-stall only works below this speed.',
    # traction control
    'TC - Enable (custom patch)': 'Turns traction control on (1) or off (0). Needs the ignition cut. When a rear wheel spins it pulls timing, then drops some sparks and closes the throttle a little, more as the spin grows. Never a full cut.',
    'TC - Slip Allowed, km/h (rear faster than front, per side) (custom patch)': 'Fixed part of the slip allowed: how much faster a rear wheel may turn than the front on its side before TC cuts.',
    'TC - Slip Allowed, plus % of road speed (custom patch)': 'Extra slip allowed as a share of road speed, so more slip is allowed when going faster. Raise it if TC cuts too early.',
    'TC - Min Speed, front wheels km/h (custom patch)': 'No TC below this front-wheel speed (the wheel sensors read about 0 at walking pace).',
    'TC - Min Pedal % (custom patch)': 'TC only acts above this pedal %, so it never cuts while you\'re off the throttle.',
    'TC - Min RPM (custom patch)': 'No TC below this rpm (a spark cut at low revs could stall the engine).',
    'TC - Full Intervention at Slip, x the allowed slip over it (custom patch)': 'How far over the allowed slip TC reaches full intervention. 1 = when a rear is slipping twice the allowed amount. Lower = TC reacts harder to the same spin.',
    'TC - Timing Pull at full intervention, deg (limit 10) (custom patch)': 'Timing taken out at full intervention, scaled down for smaller slip. The first and smoothest thing TC does. Capped at 10 deg in code.',
    'TC - Spark Cuts start at intervention % (custom patch)': 'Below this intervention level TC only pulls timing and throttle. Above it, it also drops sparks, more often as the slip grows, up to 1 call in 2: never two in a row, never a full cut.',
    'TC - Throttle Reduction at full intervention, % (limit 50) (custom patch)': 'How much the throttle is closed at full intervention (the engine-side pedal is scaled down). 0 = TC never touches the throttle. Capped at 50% in code.',
    'TC - Ease Off Rate, level steps per call (255 = full) (custom patch)': 'How quickly TC gives the power back once the slip falls: 4 takes about 0.35 s from full to nothing, so the tyres don\'t break loose again.',
    'TC - Max Intervention Time, calls ~5.5 ms (custom patch)': 'Safety backstop: TC never intervenes longer than this without a break (180 calls is about 1 s), for example if a wheel sensor fails.',
    'TC - Rest after Max Intervention Time, calls ~5.5 ms (custom patch)': 'After the Max Intervention Time, no intervention at all for this long (30 calls is about 165 ms).',
    'TC - Lockout after Clutch Release, calls (custom patch)': 'No TC for this long after the clutch comes up (calls of ~5.5 ms; 20 is about 0.1 s).',
    # overrun crackle
    'Overrun - Enable (custom patch)': 'Turns the timed overrun crackle on (1) or off (0).',
    'Overrun - Strength (spark aggressiveness), 0 = mild 100 = aggressive (custom patch)': 'How much the timing is retarded during a burst: between "Retard at Strength 0" and "Retard at Strength 100".',
    'Overrun - Duration after lift-off (custom patch)': 'How long each burst lasts after you lift off, in seconds (max 5).',
    'Overrun - Min RPM (custom patch)': 'No crackle below this rpm.',
    'Overrun - Max RPM (custom patch)': 'No crackle above this rpm.',
    'Overrun - Min Speed (custom patch)': 'No crackle below this speed (0 = any speed).',
    'Overrun - Min Coolant Temp (custom patch)': 'No crackle until the engine is at least this warm.',
    'Overrun - Arm: pedal above this before lift-off (custom patch)': 'A burst only happens after the pedal has been above this, so a gentle lift doesn\'t crackle.',
    'Overrun - Closed pedal: at or below this counts as lifted (custom patch)': 'Pedal at or below this counts as off the throttle.',
    'Overrun - Clutch pressed: allow below this speed, 0 = never (custom patch)': 'Allows crackle with the clutch down below this speed; 0 = the clutch always stops it.',
    'Overrun - Retard at Strength 0 (custom patch)': 'Timing retard during a burst at Strength 0 (mild).',
    'Overrun - Retard at Strength 100 (custom patch)': 'Timing retard during a burst at Strength 100 (aggressive). Max 45 degrees.',
    'Overrun - Task calls per second (timing calibration) (custom patch)': 'How often the overrun code runs, used to time the burst. Leave it unless a burst lasts the wrong time on the car.',
    'Overrun - Sport Mode Only: TCS off, or DSC pressed twice quickly (custom patch)': '1 = crackle only with TCS off, or after pressing DSC off then on quickly (sport mode).',
    'Overrun - Sport Mode Toggle Window, s (custom patch)': 'How quickly DSC must be pressed off then on again to toggle sport mode.',
    'Overrun - TCS Off RAM Address [hex] (custom patch)': 'Where the ECU keeps the TCS on/off state (found by NC Patcher\'s TCS check in tab 1).',
}


def auto(t):
    """a description built from the definition, for tables without one"""
    s = t.scaling
    rng = f', range {s.min:g} to {s.max:g}' if s.min is not None and s.max is not None else ''
    return f'Factory value ({t.category or "no category"}): {s.units or "no units given"}{rng}. Double-click to add your own description.'


def for_table(t, notes):
    return notes.get(t.name) or PATCH.get(t.name) or auto(t)
