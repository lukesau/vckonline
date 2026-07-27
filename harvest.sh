#!/bin/bash
cd ~/vcko_agent
pkill -f agent.selfplay || true
pkill -f run_deep2p || true
pkill -f run_generation || true
sleep 4
mkdir -p harvest
for f in data/deep2p_2k_chunk*.jsonl.gz data/mp3p_search_chunk*.jsonl.gz data/mp4p_search_chunk*.jsonl.gz data/mp5p_search_chunk*.jsonl.gz; do
  [ -f "$f" ] || continue
  zcat "$f" 2>/dev/null | gzip -6 > "harvest/$(basename $f)"
done
cd harvest && ls | wc -l && du -sh . && tar -cf ~/vcko_harvest.tar *.jsonl.gz && echo HARVEST_READY
