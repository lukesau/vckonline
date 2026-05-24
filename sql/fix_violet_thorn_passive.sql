-- Fill in The Violet Thorn's passive using the generic action-event manipulate grammar.
-- Grammar: action.<verb> manipulate_resources mode=gain gain=<g|s|m|v>:<int>
--   verb:     start | end | hire | slay | (future: build, ...)
--   mode:     gain (player-targeted modes route through the action.end queue instead)
--   gain:    resource:amount granted to the active player on the event
-- Same shape Forgotten Sorrows already uses ("action.hire manipulate_resources mode=gain gain=m:1").
-- Card text: "During your Action Phase, when you slay a Monster gain 1mp"
USE vckonline;

UPDATE domains
SET passive_effect = 'action.slay manipulate_resources mode=gain gain=m:1'
WHERE name = 'The Violet Thorn';
