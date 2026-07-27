#!/bin/bash
cd ~/vcko_agent
mkdir -p data logs
rm -f ALL_DONE
PY=.venv/bin/python
for c in $(seq 0 17); do
  nice -n 10 $PY -m agent.selfplay --games 250 --seed $((70000 + c * 1000)) \
    --policy mcts-nn --iterations 500 --turn-priors --record-visits \
    --store-states data/deep2p_chunk$c.jsonl.gz > logs/deep2p_$c.log 2>&1 &
done
for c in $(seq 0 5); do
  nice -n 10 $PY -m agent.selfplay --games 240 --seed $((90000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 3 \
    --store-states data/mp3p_search_chunk$c.jsonl.gz > logs/mp3p_$c.log 2>&1 &
done
for c in $(seq 0 4); do
  nice -n 10 $PY -m agent.selfplay --games 180 --seed $((97000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 4 \
    --store-states data/mp4p_search_chunk$c.jsonl.gz > logs/mp4p_$c.log 2>&1 &
done
for c in $(seq 0 4); do
  nice -n 10 $PY -m agent.selfplay --games 145 --seed $((103000 + c * 1000)) \
    --policy mcts-nn --iterations 300 --turn-priors --record-visits --players 5 \
    --store-states data/mp5p_search_chunk$c.jsonl.gz > logs/mp5p_$c.log 2>&1 &
done
wait
touch ALL_DONE
