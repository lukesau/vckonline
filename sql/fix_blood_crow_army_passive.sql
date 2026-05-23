-- Complete the Blood Crow Army passive_effect string.
-- Card text: "At the start of your Action Phase, you gain 1sp."
USE vckonline;

UPDATE domains
SET passive_effect = 'action.start manipulate_resources mode=gain gain=s:1'
WHERE name = 'Blood Crow Army';
