"""Tool-number mapping is explicit: catalog tool numbers are not job T slots."""
import json
from importlib.resources import files


def catalog():
    return json.loads(files("cnc_sim").joinpath("data/tool_catalog.json").read_text(encoding="utf-8"))


def resolve_tool_spec(spec):
    if "catalog_id" not in spec:return dict(spec)
    data=catalog()["tools"]
    identifier=spec["catalog_id"]
    matches=[x for x in data if x["id"]==identifier or x["name"]==identifier]
    if not matches:
        defaults=json.loads(files("cnc_sim").joinpath("data/default_machine.json").read_text(encoding="utf-8"))
        alias=defaults.get("provenance",{}).get("tool_name_aliases",{}).get(identifier)
        if alias is not None:matches=[x for x in data if x["id"]==alias]
    if len(matches)!=1:raise ValueError(f"Catalog tool {identifier!r} did not match exactly one entry")
    merged=dict(matches[0]["spec"])
    merged.update({k:v for k,v in spec.items() if k!="catalog_id"})
    merged["catalog_id"]=matches[0]["id"]
    return merged

