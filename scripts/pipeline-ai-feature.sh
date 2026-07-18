#!/usr/bin/env bash
# AI-feature pipeline: build a RAG / LLM feature with a real quality gate.
# Works greenfield or on top of the brownfield front (pass a repo to map first).
# The key difference: the gate is EVAL THRESHOLDS, not just unit tests.
set -euo pipefail
GOAL="${1:?usage: pipeline-ai-feature.sh \"<AI feature goal>\" [path-to-existing-repo]}"
REPO="${2:-}"

stage(){ echo; echo "########## $1 ##########"; }
ask(){ claude -p "$1" --permission-mode acceptEdits; }

if [ -n "$REPO" ]; then
  stage "0  Map the codebase (codebase-analyst)"
  ask "As codebase-analyst: map $REPO and note where this AI feature integrates. Goal: $GOAL"
fi

stage "2-3 Requirements (product-manager)"
ask "As product-manager: requirements + tickets for the AI feature: $GOAL. Include the quality bar (what 'good answer' means)."

stage "6  RAG/AI design (architect + ai-engineer)"
ask "As architect with ai-engineer: design the pipeline using the rag-architecture skill. ADRs for embedding model, chunking, and index choices. Web-search current best practice."

stage "8a Data ingestion (ai-engineer / database-engineer)"
ask "As ai-engineer: build ingestion -> parse -> chunk -> embed -> store, with provenance. Note corpus trust boundaries."

stage "8b Implement retrieval + generation (ai-engineer)"
ask "As ai-engineer: implement hybrid retrieval (BM25 + vector + RRF), reranking if needed, prompt assembly (versioned prompts), and generation with grounded citations. Wire eval hooks."

stage "EVAL GATE  AI quality (ai-eval-engineer)"
ask "As ai-eval-engineer: build the gold dataset and run the ai-eval harness (recall@k, MRR, faithfulness, hallucination rate, cost/latency). Report against thresholds. A regression BLOCKS."

stage "11 AI security (security-engineer)"
ask "As security-engineer: apply the llm-threat-model skill — direct + INDIRECT prompt injection, data exfiltration, insecure output handling, knowledge-base poisoning, excessive agency. Critical/High block."

stage "12-14 Performance / Docs / Release"
ask "As performance-engineer (cost+latency), docs-writer, release-manager: benchmark, document, assemble go/no-go. STOP before merge/deploy."

echo; echo "Founder approval boundary reached. AI feature ships only if eval thresholds AND security gate are green."
