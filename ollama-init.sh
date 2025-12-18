#!/bin/sh
set -e

MODEL="${OLLAMA_MODEL:-mistral}"

echo "Starting Ollama server in background..."
ollama serve &


echo "Waiting for Ollama to be ready..."
until curl -s http://localhost:11434/api/tags >/dev/null 2>&1; do
  sleep 1
done

echo "Ollama is ready"


if ! ollama list | awk '{print $1}' | grep -Fxq "$MODEL"; then
  echo "⬇ Pulling model: $MODEL"
  ollama pull "$MODEL"
else
  echo "Model already present: $MODEL"
fi

wait
