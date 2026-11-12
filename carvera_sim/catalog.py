"""Tool-number mapping is explicit: catalog tool numbers are not job T slots."""
import json
from importlib.resources import files


def catalog():
    return json.loads(files("carvera_sim").joinpath("data/makera_catalog.json").read_text(encoding="utf-8"))


def resolve_tool_spec(spec):
    if "catalog_id" not in spec:return dict(spec)
    data=catalog()["tools"]
    identifier=spec["catalog_id"]
    matches=[x for x in data if x["id"]==identifier or x["name"]==identifier]
    if len(matches)!=1:raise ValueError(f"Catalog tool {identifier!r} did not match exactly one entry")
    merged=dict(matches[0]["spec"])
    merged.update({k:v for k,v in spec.items() if k!="catalog_id"})
    merged["catalog_id"]=matches[0]["id"]
    return merged

