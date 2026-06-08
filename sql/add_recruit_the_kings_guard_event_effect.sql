-- Recruit the King's Guard (event 10, expansion "kingsguard").
-- "Immediately place the King's Guard Citizen stack into play."
--
-- This is the only event that introduces a brand-new citizen stack. The engine
-- (engines/events.py) recognises the opaque `place_kings_guard` activation key
-- and, on reveal, drops the set-aside King's Guard citizens (citizens row with
-- expansion = 'kingsguard' AND special_citizen = 1) on top of the event card so
-- they can be hired like any other board stack. When the event un-exhausts the
-- un-hired guards are pulled back to reserve until it is re-revealed.
USE vckonline;

UPDATE events
SET has_activation_effect = 1,
    activation_effect = 'place_kings_guard'
WHERE id_events = 10;
