#!/bin/bash
# Post-7bc2362 regeneration: fixed engine, fresh seeds. Harvestable anytime
# (records stream per game). Sentinel: GEN_V2_DONE when everything finishes.
cd ~/vcko_agent
PY=.venv/bin/python
for c in $(seq 0 17); do
  nice -n 10 $PY -m agent.selfplay --games 130 --seed $((200000 + c * 1000)) \
    --policy mcts-nn --iterations 2000 --turn-priors --record-visits \
    --store-states data/deep2p_2k_chunk$c.jsonl.gz > logs/deep2p_2k_$c.log 2>&1 &
done
for c in $(seq 0 5); do
  nice -n 10 $PY -m agent.selfplay --games 240 --seed $((300000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 3 \
    --store-states data/mp3p_search_chunk$c.jsonl.gz > logs/mp3p_$c.log 2>&1 &
done
for c in $(seq 0 4); do
  nice -n 10 $PY -m agent.selfplay --games 180 --seed $((310000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 4 \
    --store-states data/mp4p_search_chunk$c.jsonl.gz > logs/mp4p_$c.log 2>&1 &
done
for c in $(seq 0 4); do
  nice -n 10 $PY -m agent.selfplay --games 145 --seed $((320000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 5 \
    --store-states data/mp5p_search_chunk$c.jsonl.gz > logs/mp5p_$c.log 2>&1 &
done
wait
touch GEN_V2_DONE
