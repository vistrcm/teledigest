#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

export API_ID=$(passage telegram/app/dopgang/api_id)
export API_HASH=$(passage telegram/app/dopgang/api_hash)
export AGE_KEY=$(age -d -i ~/age.identities/age-yubikey-identity-eaba03b8-m1nano.txt dev.key.age)
export OPENAI_API_KEY=$(passage openai/tokens/dopgang-dev)

pipenv run python main.py
