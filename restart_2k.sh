#!/bin/bash
# Kill the 1000-iter 2p cohort (pattern lives only in this file, not the ssh
# command line), purge its partial output, and relaunch at 2000 iterations.
cd ~/vcko_agent
pkill -f "deep2p_1k" || true
sleep 3
rm -f data/deep2p_1k_chunk*.jsonl.gz logs/deep2p_1k_*.log DEEP2P_DONE

cat > run_deep2p_2000.sh << "EOF"
#!/bin/bash
cd ~/vcko_agent
PY=.venv/bin/python
for c in $(seq 0 17); do
  nice -n 10 $PY -m agent.selfplay --games 130 --seed $((70000 + c * 1000)) \
    --policy mcts-nn --iterations 2000 --turn-priors --record-visits \
    --store-states data/deep2p_2k_chunk$c.jsonl.gz > logs/deep2p_2k_$c.log 2>&1 &
done
wait
touch DEEP2P_DONE
EOF
chmod +x run_deep2p_2000.sh
nohup bash run_deep2p_2000.sh > logs/run_deep2p_2k.log 2>&1 < /dev/null &
sleep 6
echo "selfplay procs: $(pgrep -c -f agent.selfplay)"
