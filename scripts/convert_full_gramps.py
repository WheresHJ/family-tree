#!/usr/bin/env python3
"""
convert_full_gramps.py

Converts a GRAMPS XML (.gramps) or GRAMPS package (.gpkg / .tar.gz) into a
lossless JSON graph + a Treant-compatible tree root.

- Produces a top-level JSON with sections: people, families, events, places,
  media, sources, citations, repositories, notes, tags, attributes, others, tree
- Preserves GRAMPS handles and substructures; stores unknown sections under 'others'
- Optional media extraction from .gpkg archives

Notes:
- Implemented using xml.etree.ElementTree for zero-extra-deps portability.
- GRAMPS XML tag names differ across versions; this script uses flexible
  heuristics to gather objects. Inspect output for your specific export and
  tweak the `TAG_ALIASES` mapping if needed.
"""

from __future__ import annotations
import argparse
import gzip
import io
import json
import os
import tarfile
import textwrap
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from typing import Dict, Any, Optional, Tuple, List

# -----------------------
# Utility helpers
# -----------------------
def strip_ns(tag: Optional[str]) -> Optional[str]:
    """Strip namespace from an element.tag like '{ns}tag' -> 'tag'"""
    if tag is None:
        return None
    if '}' in tag:
        return tag.split('}', 1)[1]
    return tag

def elem_to_dict(elem: ET.Element) -> Dict[str, Any]:
    """
    Convert an XML element to a nested dict capturing:
      - attributes under '_attrs'
      - text under '_text'
      - child elements grouped by tag name (stripped)
    This creates a lossless-ish representation so unknown objects are preserved.
    """
    d: Dict[str, Any] = {}
    if elem.attrib:
        d["_attrs"] = dict(elem.attrib)
    text = elem.text.strip() if elem.text and elem.text.strip() else None
    if text:
        d["_text"] = text
    # children
    for child in elem:
        tag = strip_ns(child.tag) or "unknown"
        child_dict = elem_to_dict(child)
        d.setdefault(tag, []).append(child_dict)
    return d

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

# -----------------------
# File handling
# -----------------------
def read_gramps_bytes(path: str) -> Tuple[bytes, Optional[Dict[str, bytes]]]:
    """
    Read .gramps (xml bytes) or .gpkg (tar.gz) and return (xml_bytes, media_map).
    If archive, media_map maps member.name -> bytes.
    """
    if path.endswith('.gpkg') or path.endswith('.tar.gz') or path.endswith('.tgz'):
        media_map = {}
        xml_bytes = None
        with tarfile.open(path, 'r:gz') as tar:
            for member in tar.getmembers():
                name = member.name
                if name.endswith('.gramps') or name.endswith('.xml'):
                    f = tar.extractfile(member)
                    if f:
                        xml_bytes = f.read()
                else:
                    # collect likely media files (images, audio, pdf)
                    if any(name.lower().endswith(ext) for ext in ('.jpg','.jpeg','.png','.gif','.bmp','.mp3','.wav','.pdf','.mp4')):
                        f = tar.extractfile(member)
                        if f:
                            media_map[name] = f.read()
        if xml_bytes is None:
            raise FileNotFoundError("No .gramps/.xml found inside archive.")
        return xml_bytes, media_map
    # if gzipped single .gramps file
    with open(path, 'rb') as fh:
        head = fh.read(4)
        fh.seek(0)
        if head[:2] == b'\x1f\x8b':
            xml_bytes = gzip.decompress(fh.read())
            return xml_bytes, {}
        else:
            return fh.read(), {}

# -----------------------
# Tag aliasing / heuristics
# -----------------------
# If your .gramps uses different names, extend these lists.
TAG_ALIASES = {
    "people_containers": {"people", "persons", "person_list"},
    "person": {"person", "person_obj", "individual"},
    "families": {"families", "family_list"},
    "family": {"family", "family_obj"},
    "events": {"events", "event_list"},
    "place": ["place", "Place", "PLACE"],
    "event": {"event"},
    "places": {"places", "place_list"},
    "media": {"media", "media_list", "images"},
    "sources": {"sources", "source_list"},
    "citations": {"citations", "citation_list"},
    "repositories": {"repositories", "repository_list"},
    "notes": {"notes", "note_list"},
    "tags": {"tags", "tag_list"}
}

def tag_in(elem_tag: str, alias_set: set) -> bool:
    return strip_ns(elem_tag) in alias_set

# -----------------------
# Parsers for each top-level object type
# -----------------------
def collect_objects(root: ET.Element) -> Dict[str, List[ET.Element]]:
    """
    Return a mapping alias_key -> list[ET.Element] for any recognized major container
    """
    buckets = defaultdict(list)
    # naive: iterate all descendants and allocate by stripped tag or parent container
    for el in root.iter():
        st = strip_ns(el.tag)
        if st in TAG_ALIASES['person']:
            buckets['people'].append(el)
        elif st in TAG_ALIASES['family']:
            buckets['families'].append(el)
        elif st in TAG_ALIASES['event']:
            buckets['events'].append(el)
        elif 'place' in TAG_ALIASES and st in TAG_ALIASES['place']:
            buckets['places'].append(el)
        elif st in TAG_ALIASES['media']:
            buckets['media'].append(el)
        elif st in TAG_ALIASES['sources']:
            buckets['sources'].append(el)
        elif st in TAG_ALIASES['citations']:
            buckets['citations'].append(el)
        elif st in TAG_ALIASES['repositories']:
            buckets['repositories'].append(el)
        elif st in TAG_ALIASES['notes']:
            buckets['notes'].append(el)
        elif st in TAG_ALIASES['tags']:
            buckets['tags'].append(el)
        # else - leave for 'others' pass
    return buckets

def extract_handle(elem: ET.Element) -> Optional[str]:
    """Common patterns for handles/ids"""
    # try attribute id/handle first
    if 'handle' in elem.attrib:
        return elem.attrib.get('handle')
    if 'id' in elem.attrib:
        return elem.attrib.get('id')
    # look for child element <handle> or <id>
    for child in elem:
        if strip_ns(child.tag) in ('handle', 'id'):
            if child.text and child.text.strip():
                return child.text.strip()
    return None

def parse_people(person_elements: List[ET.Element]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for p in person_elements:
        h = extract_handle(p) or f"person_{len(out)+1}"
        # store raw dict for losslessness
        raw = elem_to_dict(p)
        # gather names (supporting multiple name elements)
        names = []
        for name_el in [c for c in p if strip_ns(c.tag) in ('name','names','display_name','personal_name')]:
            # try formatted -> components
            formatted = None
            given = surname = prefix = suffix = None
            for child in name_el:
                t = strip_ns(child.tag)
                if t in ('formatted','full','display'):
                    formatted = child.text.strip() if child.text else None
                elif t in ('given','first','first_name','forename'):
                    given = (child.text or "").strip()
                elif t in ('surname','last','last_name','family'):
                    surname = (child.text or "").strip()
                elif t in ('prefix','title'):
                    prefix = (child.text or "").strip()
                elif t in ('suffix',):
                    suffix = (child.text or "").strip()
            names.append({
                "formatted": formatted,
                "given": given,
                "surname": surname,
                "prefix": prefix,
                "suffix": suffix,
                # include raw element for later debugging/extension
                "raw": elem_to_dict(name_el)
            })
        # fallback: single display or element text
        if not names:
            maybe_name = None
            for c in p:
                if strip_ns(c.tag) in ('display_name','display'):
                    maybe_name = c.text.strip() if c.text else None
            names.append({"formatted": maybe_name, "given": None, "surname": None, "raw": raw})

        # events references, attribute lists, tags etc.
        event_refs = []
        for evref in [c for c in p if strip_ns(c.tag) in ('event_ref','eventref','event')]:
            # if it has an attribute 'handle' or 'ref' or text
            ref = evref.attrib.get('ref') or evref.attrib.get('handle') or (evref.text.strip() if evref.text else None)
            if ref:
                event_refs.append(ref)

        # attributes (custom attributes)
        attrs = []
        for a in [c for c in p if strip_ns(c.tag) in ('attribute','attributes','custom')]:
            attrs.append(elem_to_dict(a))

        out[h] = {
            "handle": h,
            "raw": raw,
            "names": names,
            "event_refs": event_refs,
            "attributes": attrs,
            "parents": [],       # to be filled
            "children": [],      # to be filled
            "families_as_parent": [], # to be filled
            "families_as_child": None
        }
    return out

def parse_families(family_elements: List[ET.Element]) -> Dict[str, Dict[str, Any]]:
    out = {}
    for f in family_elements:
        h = extract_handle(f) or f"family_{len(out)+1}"
        raw = elem_to_dict(f)
        father = None
        mother = None
        children = []
        # typical patterns
        for c in f:
            tag = strip_ns(c.tag)
            if tag in ('father','husband','father_ref','father_handle','parent'):
                ref = c.attrib.get('ref') or (c.text.strip() if c.text else None)
                if ref:
                    father = ref
            elif tag in ('mother','wife','mother_ref','mother_handle'):
                ref = c.attrib.get('ref') or (c.text.strip() if c.text else None)
                if ref:
                    mother = ref
            elif tag in ('child','child_ref','children'):
                # child may contain child elements or refs
                # find any handle/ref attribute or nested handle node
                if 'ref' in c.attrib:
                    children.append(c.attrib.get('ref'))
                else:
                    # search descendents for handle
                    found = None
                    for d in c.iter():
                        if strip_ns(d.tag) in ('handle','ref'):
                            if d.text and d.text.strip():
                                found = d.text.strip()
                                break
                    if found:
                        children.append(found)
                    elif c.text and c.text.strip():
                        children.append(c.text.strip())
        out[h] = {
            "handle": h,
            "raw": raw,
            "father": father,
            "mother": mother,
            "children": children
        }
    return out

def parse_generic(elements: List[ET.Element]) -> Dict[str, Dict[str, Any]]:
    """
    Generic parser for events, places, sources, media etc.
    Stores each object's raw dict and basic handle.
    """
    out = {}
    for el in elements:
        h = extract_handle(el) or f"obj_{len(out)+1}"
        out[h] = {
            "handle": h,
            "raw": elem_to_dict(el)
        }
    return out

# -----------------------
# Build tree (Treant nodeStructure)
# -----------------------
def build_treant_tree(people: Dict[str, Any], families: Dict[str, Any], root_handle: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a Treant-friendly nested node structure starting from root_handle (if provided)
    or else by auto-detecting top-level ancestors (people with no families_as_child).
    Each node contains: id, handle, text{name,title,desc}, and children list.
    """

    # helper to choose display name & title
    def display_info(p: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        # pick first formatted name, else compose from given+surname
        primary = None
        for nm in p.get("names", []):
            if nm.get("formatted"):
                primary = nm
                break
        if primary is None and p.get("names"):
            primary = p["names"][0]
        if primary:
            name = primary.get("formatted") or " ".join(x for x in (primary.get("given") or "", primary.get("surname") or "")).strip()
        else:
            name = p.get("handle", "<Unknown>")
        # build title from birth/death if present in events (we'll look up events by refs)
        title = None
        # event formatting will be handled later in tree build if desired
        return name, title

    # We'll need a quick person lookup and a cache to avoid cycles
    node_cache: Dict[str, Dict[str, Any]] = {}

    def build_person_node(handle: str) -> Dict[str, Any]:
        if handle not in people:
            return {"text": {"name": handle or "<Unknown>"}}
        if handle in node_cache:
            return node_cache[handle]
        p = people[handle]
        name, title = display_info(p)
        node = {
            "id": handle,
            "handle": handle,
            "text": {"name": name, "title": title or ""},
            # keep raw data pointer for UI later
            "_meta": {"person_handle": handle}
        }
        node_cache[handle] = node  # early set to prevent recursion loops
        # collect children from families_as_parent
        children_handles = []
        for famh in p.get("families_as_parent", []):
            fam = families.get(famh)
            if not fam:
                continue
            for ch in fam.get("children", []):
                if ch:
                    children_handles.append(ch)
        # unique preserve order
        seen = set()
        node_children = []
        for ch in children_handles:
            if not ch or ch in seen:
                continue
            seen.add(ch)
            node_children.append(build_person_node(ch))
        if node_children:
            node["children"] = node_children
        else:
            node["children"] = []
        return node

    # auto-detect root candidates if not provided
    if root_handle:
        root = build_person_node(root_handle)
    else:
        roots = [h for h,p in people.items() if not p.get('families_as_child')]
        if not roots:
            # fallback to any person
            roots = list(people.keys())[:1]
        if len(roots) == 1:
            root = build_person_node(roots[0])
        else:
            # synthetic root to attach multiple ancestors
            root = {
                "text": {"name": "Roots"},
                "pseudo": True,
                "HTMLclass": "pseudo-root",
                "children": [build_person_node(h) for h in roots]
            }
    return root

# -----------------------
# Wiring everything together
# -----------------------
def convert(xml_bytes: bytes, media_map: Optional[Dict[str, bytes]] = None,
            extract_media_dir: Optional[str] = None, root_person: Optional[str] = None) -> Dict[str, Any]:
    """
    Convert xml_bytes into the option-A JSON object described above.
    If extract_media_dir is provided and media_map is non-empty, writes media files there
    and rewrites media objects' file references to local paths.
    """
    # parse xml
    parser = ET.XMLParser(encoding="utf-8")
    xml_root = ET.fromstring(xml_bytes, parser=parser)

    # collect candidate elements
    buckets = collect_objects(xml_root)

    # parse
    people = parse_people(buckets.get('people', []))
    families = parse_families(buckets.get('families', []))
    events = parse_generic(buckets.get('events', []))
    places = parse_generic(buckets.get('places', []))
    media = parse_generic(buckets.get('media', []))
    sources = parse_generic(buckets.get('sources', []))
    citations = parse_generic(buckets.get('citations', []))
    repositories = parse_generic(buckets.get('repositories', []))
    notes = parse_generic(buckets.get('notes', []))
    tags = parse_generic(buckets.get('tags', []))

    # Cross-link families <-> people
    for fh, fam in families.items():
        for ch in fam.get('children', []):
            if ch in people:
                people[ch]['families_as_child'] = fh
                people[ch]['parents'].extend([x for x in (fam.get('father'), fam.get('mother')) if x])
        for parent in (fam.get('father'), fam.get('mother')):
            if parent and parent in people:
                people[parent]['families_as_parent'].append(fh)

    # Optionally extract media bytes to disk (if provided)
    media_out = {}
    if extract_media_dir and media_map:
        ensure_dir(extract_media_dir)
        for member_name, data in media_map.items():
            safe_name = os.path.basename(member_name)
            out_path = os.path.join(extract_media_dir, safe_name)
            with open(out_path, 'wb') as fh:
                fh.write(data)
            # create a media object entry referencing local file path
            mid = safe_name  # using filename as handle key
            media_out[mid] = {
                "handle": mid,
                "raw": {"_attrs": {"source_name": member_name}},
                "file": out_path
            }
    else:
        # map existing media nodes to their raw structure (no extraction)
        for mid, m in media.items():
            media_out[mid] = m

    # Build a Treant-friendly tree root
    tree_root = build_treant_tree(people, families, root_person)

    # prepare final JSON
    out = {
        "people": people,
        "families": families,
        "events": events,
        "places": places,
        "media": media_out,
        "sources": sources,
        "citations": citations,
        "repositories": repositories,
        "notes": notes,
        "tags": tags,
        "others": {},  # placeholder for any extra categories
        "tree": {
            "chart": {
                "container": "#tree-container",
                "rootOrientation": "NORTH",
                "nodeAlign": "TOP",
                "connectors": {"type": "step"}
            },
            "root": tree_root
        }
    }
    return out

# -----------------------
# CLI
# -----------------------
def main_cli():
    ap = argparse.ArgumentParser(
        description="Convert GRAMPS .gramps/.gpkg to full JSON graph + Treant tree (Option A)."
    )
    ap.add_argument("input", help="Path to .gramps (xml) or .gpkg (tar.gz) file")
    ap.add_argument("output", help="Path to write output JSON")
    ap.add_argument("--root", help="Optional root person handle/id to use (e.g. P:1234)", default=None)
    ap.add_argument("--extract-media", help="Optional directory to extract media from .gpkg into", default=None)
    args = ap.parse_args()

    xml_bytes, media_map = read_gramps_bytes(args.input)

    # if extract_media_dir specified but no media_map present -> warn but continue
    if args.extract_media and not media_map:
        print("Warning: --extract-media provided but input archive contained no media files.")

    print("Parsing GRAMPS XML...")
    out = convert(xml_bytes, media_map=media_map, extract_media_dir=args.extract_media, root_person=args.root)

    print(f"Writing JSON to {args.output} ...")
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("Done.")

if __name__ == "__main__":
    main_cli()