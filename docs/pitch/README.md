# Pitch deck

`AabFlow-pitch.pptx` (13 slides, native charts, Morph transitions, staged entrance animations).
Numbers come from stored runs and evidence; see `docs/TALKING_POINTS.md` for each source.
Speaker notes are in the deck.

Rebuild (Docker only; the tools live in throwaway containers, nothing is installed in the project):

1. Screenshots from the real app (frozen demo running, seeded session):
   `docker compose --profile test run --rm --no-deps e2e node ../scripts/deck_shots.mjs`
   → `docs/pitch/shots/*.png`
2. Deck: run `build_deck.js` with `pptxgenjs@3.12.0` available (e.g. a node container with a
   scratch `node_modules`), then `python3 animate_deck.py raw.pptx AabFlow-pitch.pptx`.

Morph needs PowerPoint 2019/365 (Keynote and LibreOffice show the fade fallback).
