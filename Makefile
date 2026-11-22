# Pinkasol playground. `make` alone builds the tile.
PY := tools/.venv/bin/python

.PHONY: tile tile-local serve serve-lan venv analyse parts edges audio upload upload-dry

# The Tilefolio code tile: dist/pinkasol-tile.html, to paste in the code
# panel (tick p5.js). Rebuilt from duo.html, lib/pinkasol-engine.js and the
# parts' manifest
tile:
	python3 tools/build.py

# The same tile for this playground: http://localhost:8121/dist/pinkasol-tile.local.html
tile-local:
	python3 tools/build.py --local

serve:
	python3 serve.py

serve-lan:
	python3 serve.py --lan

# The audio pipeline (needs audio/full and audio/stems, see README)
venv: tools/.venv/bin/python
tools/.venv/bin/python:
	python3 -m venv tools/.venv
	tools/.venv/bin/pip install -q numpy librosa soundfile

analyse: venv
	$(PY) -W ignore tools/analyse.py

parts: venv
	$(PY) tools/cut.py

edges: venv
	$(PY) -W ignore tools/edges.py

# Everything from the stems: bars and parts, cut, then the tile
audio: analyse parts tile

# The part files to picasol.fr's media library, as its owner (writes to
# production; the password is asked): fills audio/media-urls.json, then the
# tile is rebuilt with their addresses
NODE ?= node
upload:
	@test -n "$(EMAIL)" || (echo "usage: make upload EMAIL=<picasol.fr owner's e-mail>"; exit 1)
	$(NODE) tools/upload.mjs --email "$(EMAIL)" --check
	python3 tools/build.py

upload-dry:
	$(NODE) tools/upload.mjs --dry-run
