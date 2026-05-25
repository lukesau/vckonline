-- Replace the old `grant_action slay` bonus-action mechanic on Eye of Asteraten
-- with the new bare-verb `slay` token. The engine now resolves "may slay a
-- Monster" effects with an immediate two-stage prompt (pick a monster -> set
-- strength/magic payment) instead of accruing a free-slay action token to
-- spend later. Compound `+` ordering is preserved: the activator gains 5sp
-- first, then the slay prompt opens with the augmented strength pool.
-- Card text: "Immediately gain 5sp and you may slay a Monster."
USE vckonline;

UPDATE domains
SET activation_effect = 's 5 + slay'
WHERE name = 'Eye of Asteraten';
