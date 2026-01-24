#!/bin/bash

# Output file will be created in the current directory
OUTPUT_FILE="6-pokemon-types.json"

TYPES_URL="https://pokeapi.co/api/v2/type/"
TYPES_JSON=$(curl -s "$TYPES_URL")

# TODO: check i'm using jq in the right way for arrays if it fails
TYPE_NAMES=$(echo "$TYPES_JSON" | jq -r '.results[].name')
TYPE_URLS=$(echo "$TYPES_JSON" | jq -r '.results[].url')

echo "[" > "$OUTPUT_FILE"

FIRST=true
for TYPE_URL in $TYPE_URLS; do
    TYPE_INFO=$(curl -s "$TYPE_URL")

    if [ "$FIRST" = true ]; then
        FIRST=false
    else
    # TODO: Check hte , is in the right place
        echo "," >> "$OUTPUT_FILE"
    fi

    echo "$TYPE_INFO" >> "$OUTPUT_FILE"

    sleep 1
done

# TODO: Manually fix the JSON to iterate later
# echo "]" >> "$OUTPUT_FILE"

echo "Data saved to $OUTPUT_FILE"