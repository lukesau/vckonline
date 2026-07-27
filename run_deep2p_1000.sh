#!/bin/bash
cd ~/vcko_agent
PY=.venv/bin/python
for c in $(seq 0 17); do
  nice -n 10 $PY -m agent.selfplay --games 125 --seed $((70000 + c * 1000)) \
    --policy mcts-nn --iterations 1000 --turn-priors --record-visits \
    --store-states data/deep2p_1k_chunk$c.jsonl.gz > logs/deep2p_1k_$c.log 2>&1 &
done
wait
touch DEEP2P_DONE
