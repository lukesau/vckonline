-- Align monster area and count-area payouts with rulebook / Constants.areas ("Mountains").
USE vckonline;

UPDATE monsters
SET area = 'Mountains'
WHERE area = 'Mountain';

UPDATE monsters
SET special_reward = REPLACE(special_reward, 'area Mountain ', 'area Mountains ')
WHERE special_reward LIKE '%area Mountain %';
