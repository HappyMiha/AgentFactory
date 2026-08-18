#!/bin/sh
set -eu

address="${TEMPORAL_ADDRESS:-temporal:7233}"
namespace="${TEMPORAL_NAMESPACE:-agentfactory}"

until temporal operator cluster health --address "$address" >/dev/null 2>&1; do
  sleep 2
done

if temporal operator namespace describe --namespace "$namespace" --address "$address" >/dev/null 2>&1; then
  echo "Namespace '$namespace' already exists"
else
  temporal operator namespace create --namespace "$namespace" --description "AgentFactory local durable workflows" --retention 7d --address "$address"
fi
