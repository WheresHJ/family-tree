# GRAMPS Family Tree Viewer

A static family tree web application powered by Treant.js, with a **full GRAMPS XML/Package → JSON converter**. This project separates the **front-end display** from the **data conversion**, making it easy to upgrade to a dynamic application later.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Project Structure](#project-structure)
- [Using the GRAMPS JSON Converter](#using-the-gramps-json-converter)
- [Static Site Setup](#static-site-setup)
- [JSON Structure Diagram](#json-structure-diagram)
- [ASCII Tree Visualization](#ascii-tree-visualization)
- [Example JSON Node](#example-json-node)
- [Future Extensions](#future-extensions)
- [Notes](#notes)
- [License](#license)

---

## Features

- Converts GRAMPS `.gramps` (XML) or `.gpkg` (package) files to a **full JSON graph**.
- Treant.js-compatible `nodeStructure` for immediate tree rendering.
- Preserves all GRAMPS objects:
  - People (with multiple names)
  - Families (parent/child links)
  - Events (birth, death, custom)
  - Places, Media, Sources, Citations, Repositories, Notes, Tags, Attributes, and more
- Optional media extraction from `.gpkg` packages.
- Modular and future-proof for dynamic applications.

---

## Requirements

- Python 3.8+
- `Treant.js` (for the front-end tree)
- GitHub Pages or any static web host

---

## Project Structure

```text
project-root/
├── data/
│   ├── tree.json         # Generated JSON from GRAMPS
│   └── media/            # Optional: extracted media files
├── js/
│   └── app.js            # Treant.js frontend loader
├── css/
│   └── style.css         # Optional custom styles
├── scripts/
│   └── convert_full_gramps.py  # GRAMPS → JSON converter
├── index.html
└── README.md
```
---

## Using the GRAMPS JSON Converter 

The converter script convert_full_gramps.py produces Option A JSON, a complete GRAMPS object graph including a Treant.js-compatible tree.root.

### 1. Basic usage
```
python scripts/convert_full_gramps.py path/to/tree.gramps data/tree.json
```
- `path/to/tree.gramps` — your GRAMPS export file (XML)
- `data/tree.json` — output JSON file

### 2. Specify a Root Person
```python scripts/convert_full_gramps.py path/to/tree.gramps data/tree.json --root P:1234```
- `--root` — the GRAMPS handle/id of the root person for the Treant tree
- If omitted, the script auto-detects a root (people with no `families_as_child`).

### 3. Extract Media from `.gpkg`
```python scripts/convert_full_gramps.py path/to/tree.gpkg data/tree.json --extract-media data/media```
- Extracts media files (photos, audio, PDF, etc.) from a GRAMPS package
- Stores files under `data/media`
- JSON `media` entries reference the local file paths

### 4. Notes
- The converter preserves raw GRAMPS XML under `raw` for all objects.
- If your GRAMPS export has unusual tag names, edit `TAG_ALIASES` in the script.
- Large trees may generate large JSON files; consider compression for deployment.

---

## Static Site Setup
1. Place `tree.json` in the `/data` folder.
2. Include `Treant.js` in index.html:
```
<link rel="stylesheet" href="https://fperucic.github.io/treant-js/Treant.css">
<script src="https://fperucic.github.io/treant-js/vendor/raphael.js"></script>
<script src="https://fperucic.github.io/treant-js/Treant.js"></script>
<script src="js/app.js"></script>
```
3. Create a container for the tree:

```
<div id="tree-container"></div>
```

4. Open `index.html` in your browser. The tree should render automatically using `tree.json`.

---

## JSON Structure Diagram

The Option A JSON output contains a graph + tree:
```
{
  "people": { ... },
  "families": { ... },
  "events": { ... },
  "places": { ... },
  "media": { ... },
  "sources": { ... },
  "citations": { ... },
  "repositories": { ... },
  "notes": { ... },
  "tags": { ... },
  "attributes": { ... },
  "others": { ... },
  "tree": {
    "chart": { ... Treant chart config ... },
    "root": { ... nested nodeStructure ... }
  }
}
```

- `people[...]` contains all individual records, names, events, attributes, and raw XML.
- `families[...]` defines parent-child relationships.
- `tree.root` is ready for Treant.js rendering.
- `_meta` fields in nodes link to full person data for potential dynamic features.

---

## ASCII Tree Visualization

Example of a tree using `tree.root`:

```
John Doe (b. 1900 – d. 1975)
├── Jane Doe
│   ├── Alice Smith
│   └── Bob Smith
└── Michael Doe
    └── Carol Doe
```

- Each node has `id` corresponding to a person's handle.
- Child nodes are nested in `children` arrays.
- Titles (birth/death) appear under `text.title`.

---

## Example JSON Node

```
{
  "id": "P:1234",
  "handle": "P:1234",
  "text": {
    "name": "John Doe",
    "title": "b. 1900 – d. 1975"
  },
  "_meta": {
    "people": {
      "names": [
        {"formatted": "John Doe", "given": "John", "surname": "Doe"}
      ],
      "events": [
        {"type": "Birth", "date": "1900-01-01"},
        {"type": "Death", "date": "1975-12-31"}
      ]
    }
  },
  "children": [
    {
      "id": "P:2345",
      "handle": "P:2345",
      "text": {"name": "Jane Doe", "title": ""},
      "children": []
    }
  ]
}
```

---

## Future app extensions
- Dynamic app support: Serve JSON via an API for interactive web apps.
- Richer node info: `_meta` fields can populate side panels with full person data.
- Media display: Render photos/videos using `media` object paths.
- Custom events/attributes: Front-end can render any stored GRAMPS object.
- Tree layout customization: Adjust `tree.chart` settings in JSON or Treant.js.

---

## Notes

- All raw GRAMPS XML is preserved in `raw` fields.
- Adjust `TAG_ALIASES` in `convert_full_gramps.py` if objects are missing.
- Large trees may produce large JSON files; compression may be needed.
- Media extraction uses file basenames; collisions should be handled manually or extended in the script.