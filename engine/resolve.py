#!/usr/bin/env python3
"""Deterministic identity pass.

Reads the current extraction's lines and appends a resolution when the line
states price-determining facts. A line with no such facts is left unresolved
and stays visible. Re-running inserts a new row and points the previous live
row at it. Identity is not a write gate: this script never creates postings
and never drops a line that does not match.

  TDV2_DSN=... python3 engine/resolve.py
  python3 engine/resolve.py --dry-run
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract  # noqa: E402

METHOD = "deterministic-attr-v1"


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else float(value)
    if isinstance(value, str) and re.fullmatch(r"\d+(\.\d+)?", value.strip()):
        number = float(value.strip())
        return int(number) if number.is_integer() else number
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _ddr(attrs: dict) -> str | None:
    blob = " ".join(str(attrs.get(k) or "") for k in ("ram_type", "ram_kind"))
    match = re.search(r"ddr\s*-?\s*([345])", blob, re.I)
    return f"ddr{match.group(1)}" if match else None


def _iface(attrs: dict) -> str | None:
    raw = attrs.get("storage_interface")
    if not isinstance(raw, str) or not raw.strip():
        return None
    token = re.split(r"[\s/]+", raw.strip())[0]
    return _slug(token) or None


def product_identity(attrs: dict) -> dict | None:
    """One identity from stated facts. None when the line does not carry any."""
    if not isinstance(attrs, dict):
        return None
    cpu = attrs.get("cpu_model")
    cpu = cpu.strip() if isinstance(cpu, str) and cpu.strip() else None
    chassis = attrs.get("chassis_model")
    chassis = chassis.strip() if isinstance(chassis, str) and chassis.strip() else None
    cap = _num(attrs.get("storage_capacity_gb"))
    kind = attrs.get("storage_kind")
    kind = kind.strip() if isinstance(kind, str) and kind.strip() else None
    dimm = _num(attrs.get("ram_dimm_gb"))

    if cpu and chassis:
        key = f"server:{_slug(cpu)}:{_slug(chassis)}"
        return {"product_key": key, "product_name": f"{chassis} / {cpu}", "confidence": 0.9, "facts": 2}
    if cpu and cap is None and dimm is None:
        return {"product_key": f"cpu:{_slug(cpu)}", "product_name": cpu, "confidence": 0.6, "facts": 1}
    if cap is not None and cpu is None:
        iface = _iface(attrs)
        kind_slug = _slug(kind) if kind else "drive"
        parts = ["drive", kind_slug]
        if iface:
            parts.append(iface)
        parts.append(f"{cap:g}gb")
        name_bits = [f"{cap:g}GB", kind or "drive"]
        if isinstance(attrs.get("storage_interface"), str):
            name_bits.append(attrs["storage_interface"].strip())
        return {
            "product_key": ":".join(parts),
            "product_name": " ".join(name_bits),
            "confidence": 0.9 if iface or kind else 0.6,
            "facts": 2 if iface or kind else 1,
        }
    if dimm is not None and cpu is None:
        family = _ddr(attrs)
        ram_kind = attrs.get("ram_kind")
        ram_kind = ram_kind.strip() if isinstance(ram_kind, str) and ram_kind.strip() else None
        speed = _num(attrs.get("ram_speed_mts"))
        parts = ["mem"]
        if family:
            parts.append(family)
        if ram_kind:
            parts.append(_slug(ram_kind))
        parts.append(f"{dimm:g}gb")
        if speed is not None:
            parts.append(str(speed))
        name = f"{dimm:g}GB"
        if family:
            name += f" {family.upper()}"
        if ram_kind:
            name += f" {ram_kind}"
        facts = 1 + (family is not None) + (ram_kind is not None)
        return {
            "product_key": ":".join(parts),
            "product_name": name,
            "confidence": 0.9 if facts >= 2 else 0.6,
            "facts": facts,
        }
    return None


def _load_lines(dsn: str) -> list[dict]:
    sql = """
SELECT json_agg(row_to_json(t)) FROM (
  SELECT l.id AS line_id, l.posting_id, l.label, l.attributes
  FROM lines l
  JOIN v_current_extractions c ON c.extraction_id = l.extraction_id
  WHERE l.parent_line_id IS NULL
) t;
"""
    rows = extract.run_psql(dsn, sql)
    if not rows or rows[0] in ("", "null"):
        return []
    return json.loads(rows[0])


def _existing(dsn: str, line_ids: list[str]) -> dict[str, dict]:
    if not line_ids:
        return {}
    doc = base64.b64encode(json.dumps({"ids": line_ids}).encode()).decode()
    sql = f"""
BEGIN;
CREATE TEMP TABLE _src AS
  SELECT convert_from(decode('{doc}','base64'),'UTF8')::jsonb AS d;
SELECT 'R:'||coalesce((
  SELECT jsonb_object_agg(line_id::text, jsonb_build_object('id', id, 'product_key', product_key))
  FROM (
    SELECT DISTINCT ON (r.line_id) r.line_id, r.id, r.product_key
    FROM resolutions r
    WHERE r.superseded_by IS NULL
      AND r.line_id = ANY (ARRAY(SELECT jsonb_array_elements_text(d->'ids') FROM _src)::uuid[])
    ORDER BY r.line_id, r.created_at DESC, r.id DESC
  ) live
)::text, '{{}}');
COMMIT;
"""
    out = extract.run_psql(dsn, sql)
    for line in out:
        if line.startswith("R:"):
            return json.loads(line[2:])
    return {}


def _write(dsn: str, inserts: list[dict], supersede: list[dict]) -> None:
    doc = base64.b64encode(json.dumps({"inserts": inserts, "supersede": supersede}).encode()).decode()
    sql = f"""
BEGIN;
CREATE TEMP TABLE _src AS
  SELECT convert_from(decode('{doc}','base64'),'UTF8')::jsonb AS d;
INSERT INTO resolutions (id, posting_id, line_id, product_key, product_name, confidence, method)
SELECT (s->>'id')::uuid, (s->>'posting_id')::uuid, (s->>'line_id')::uuid,
       s->>'product_key', s->>'product_name', (s->>'confidence')::numeric, s->>'method'
FROM (SELECT d FROM _src) x, jsonb_array_elements(x.d->'inserts') s;
UPDATE resolutions r
SET superseded_by = (s->>'superseder')::uuid
FROM (SELECT d FROM _src) x, jsonb_array_elements(x.d->'supersede') s
WHERE r.id = (s->>'id')::uuid;
COMMIT;
"""
    extract.run_psql(dsn, sql)


def plan(lines: list[dict], existing: dict[str, dict]) -> tuple[list[dict], list[dict], dict]:
    inserts = []
    supersede = []
    counts = {"lines": len(lines), "resolved": 0, "unresolved": 0, "unchanged": 0}
    for line in lines:
        identity = product_identity(line.get("attributes") or {})
        if identity is None:
            counts["unresolved"] += 1
            continue
        prior = existing.get(line["line_id"])
        if prior and prior.get("product_key") == identity["product_key"]:
            counts["unchanged"] += 1
            counts["resolved"] += 1
            continue
        new_id = extract.uuid7()
        inserts.append({
            "id": new_id,
            "posting_id": line["posting_id"],
            "line_id": line["line_id"],
            "product_key": identity["product_key"],
            "product_name": identity["product_name"],
            "confidence": identity["confidence"],
            "method": METHOD,
        })
        if prior:
            supersede.append({"id": prior["id"], "superseder": new_id})
        counts["resolved"] += 1
    return inserts, supersede, counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Deterministic resolution pass")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    dsn = os.environ.get("TDV2_DSN")
    if not dsn:
        print("TDV2_DSN not set", file=sys.stderr)
        return 2
    lines = _load_lines(dsn)
    existing = _existing(dsn, [ln["line_id"] for ln in lines])
    inserts, supersede, counts = plan(lines, existing)
    print(json.dumps({"method": METHOD, **counts, "inserts": len(inserts), "supersede": len(supersede)}))
    if args.dry_run or not inserts:
        return 0
    _write(dsn, inserts, supersede)
    return 0


if __name__ == "__main__":
    sys.exit(main())
