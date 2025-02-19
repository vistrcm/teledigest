#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

pipenv run python main.py
