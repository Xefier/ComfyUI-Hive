#!/usr/bin/env python3
"""Turns a ComfyUI workflow template (the editor's format, with subgraphs) into the API format that POST /prompt takes.

Build-time only: tools/build.py runs it for every workflow in the catalog and the miner ships the result. It needs the
node definitions of the ComfyUI version the miner installs (GET /object_info of that version, saved as JSON), because
the editor's format stores a node's settings as an unnamed list (widgets_values) that only the definition can name.

What it does, the same way the editor's own "Export (API)" does:
- subgraphs are expanded into their nodes, with ids "<instance>:<inner>" (nested: "<a>:<b>:<c>");
- notes, reroutes and muted nodes (mode 2) are left out, and bypassed nodes (mode 4) pass their input of the same type
  through;
- a subgraph's promoted widgets (the settings shown on the subgraph's own node) are listed by their label, so the
  miner can set "text", "width", ... without knowing which inner node they belong to.

Standard library only.
"""

import json
import sys

VIRTUAL = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "Label (rgthree)"}
WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
SUBGRAPH_INPUT = -10
SUBGRAPH_OUTPUT = -20


class ConvertError(Exception):
    pass


def norm_links(links):
    """Top-level links are lists, a subgraph's are objects: both become {id: (origin, origin_slot, target, slot, type)}."""
    out = {}
    for link in links or []:
        if isinstance(link, dict):
            out[link["id"]] = (link["origin_id"], link["origin_slot"], link["target_id"], link["target_slot"],
                               link.get("type"))
        else:
            out[link[0]] = (link[1], link[2], link[3], link[4], link[5] if len(link) > 5 else None)
    return out


class Graph:
    """One level: the top of the workflow, or the inside of one subgraph instance."""

    def __init__(self, nodes, links, prefix, parent=None, instance=None, definition=None):
        self.nodes = {n["id"]: n for n in nodes}
        self.links = norm_links(links)
        self.prefix = prefix
        self.parent = parent
        self.instance = instance  # the node in the parent that this graph is the inside of
        self.definition = definition

    def flat_id(self, node_id):
        return f"{self.prefix}{node_id}"


class Converter:
    def __init__(self, workflow, object_info):
        self.workflow = workflow
        self.info = object_info
        self.subgraphs = {s["id"]: s for s in workflow.get("definitions", {}).get("subgraphs", [])}
        self.prompt = {}
        self.params = {}  # label of a promoted widget -> [flat node id, input name]

    # --- widgets ------------------------------------------------------------------------------------------------

    def read_widgets(self, inputs, order, values, out, prefix=""):
        """Names the values of widgets_values, which the editor stores in the order of the node's inputs: required, then
        optional. Some widgets keep an extra value after their own (a seed's "control after generate", an image's
        upload button). A dynamic setting (COMFY_DYNAMICCOMBO_V3) keeps the option chosen, then that option's own
        settings, which the API names "<setting>.<own setting>"."""
        for section in ("required", "optional"):
            for name in order.get(section, []):
                entry = inputs.get(section, {}).get(name)
                if entry is None:
                    continue
                kind = entry[0]
                opts = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
                if opts.get("forceInput"):
                    continue
                if kind == "COMFY_DYNAMICCOMBO_V3":
                    if not values:
                        return
                    key = values.pop(0)
                    out[prefix + name] = key
                    option = next((o for o in opts.get("options", []) if o["key"] == key), None)
                    if option is None:
                        raise ConvertError(f"{name}: no option {key!r}")
                    nested = option.get("inputs", {})
                    nested_order = {k: list(v) for k, v in nested.items()}
                    self.read_widgets(nested, nested_order, values, out, f"{prefix}{name}.")
                    continue
                if kind == "COMFY_AUTOGROW_V3":
                    # A growing list of inputs ("values.a", "images.image_1", ...): no widgets, as long as each is a
                    # socket (a type like IMAGE, or several types at once)
                    template = opts.get("template", {}).get("input", {})
                    kinds = [e[0] for part in template.values() for e in part.values()]
                    if all(isinstance(k, str) and k not in WIDGET_TYPES for k in kinds):
                        continue
                if kind in ("COMFY_AUTOGROW_V3", "COMFY_DYNAMICGROUP_V3"):
                    raise ConvertError(f"{name}: settings of kind {kind} are not handled yet")
                if not (isinstance(kind, list) or kind in WIDGET_TYPES):
                    continue
                if not values:
                    return
                out[prefix + name] = values.pop(0)
                if opts.get("control_after_generate") and values:
                    values.pop(0)
                if (opts.get("image_upload") or opts.get("video_upload") or opts.get("audio_upload")) and values:
                    values.pop(0)

    def widget_values(self, node):
        values = node.get("widgets_values")
        if isinstance(values, dict):
            return {k: v for k, v in values.items() if k in self.input_names(node["type"])}
        spec = self.info[node["type"]]
        inputs = spec["input"]
        order = spec.get("input_order") or {k: list(v) for k, v in inputs.items()}
        out = {}
        try:
            self.read_widgets(inputs, order, list(values or []), out)
        except ConvertError as error:
            raise ConvertError(f"node {node['id']} ({node['type']}): {error}") from None
        return out

    def input_names(self, class_type):
        spec = self.info[class_type]["input"]
        return set(spec.get("required", {})) | set(spec.get("optional", {}))

    # --- following links ----------------------------------------------------------------------------------------

    def resolve(self, graph, link_id):
        """Where the value carried by a link in this graph comes from: ("node", flat id, slot), ("value", v), or None."""
        if link_id is None or link_id not in graph.links:
            return None
        origin, slot, _target, _tslot, ltype = graph.links[link_id]
        return self.resolve_output(graph, origin, slot, ltype)

    def resolve_output(self, graph, origin, slot, ltype):
        if origin == SUBGRAPH_INPUT:
            # The value comes into the subgraph from outside: through the instance's input of the same position
            definition, instance, parent = graph.definition, graph.instance, graph.parent
            name = definition["inputs"][slot]["name"]
            for entry in instance.get("inputs", []):
                if entry["name"] == name:
                    return self.resolve(parent, entry.get("link"))
            return None
        node = graph.nodes.get(origin)
        if node is None:
            raise ConvertError(f"link from missing node {origin} in {graph.prefix or 'top'}")
        mode = node.get("mode", 0)
        if node["type"] in self.subgraphs:
            inner = self.inner_graph(graph, node)
            out = self.subgraphs[node["type"]]["outputs"][slot]
            for link_id in out.get("linkIds", []):
                return self.resolve(inner, link_id)
            return None
        if node["type"] == "Reroute":
            return self.resolve(graph, node["inputs"][0].get("link"))
        if node["type"] == "PrimitiveNode":
            return ("value", (node.get("widgets_values") or [None])[0])
        if mode == 2:
            return None
        if mode == 4:
            # Bypassed: the first input of the output's type stands in for it
            out_type = node["outputs"][slot]["type"] if slot < len(node.get("outputs", [])) else ltype
            for entry in node.get("inputs", []):
                if entry.get("type") == out_type and entry.get("link") is not None:
                    return self.resolve(graph, entry["link"])
            return None
        return ("node", graph.flat_id(node["id"]), slot)

    def inner_graph(self, graph, instance):
        definition = self.subgraphs[instance["type"]]
        return Graph(definition["nodes"], definition.get("links"), f"{graph.flat_id(instance['id'])}:", graph,
                     instance, definition)

    # --- the walk -----------------------------------------------------------------------------------------------

    def convert(self):
        top = Graph(self.workflow["nodes"], self.workflow.get("links"), "")
        self.walk(top)
        return self.prompt

    def walk(self, graph):
        for node in graph.nodes.values():
            kind = node["type"]
            mode = node.get("mode", 0)
            if kind in VIRTUAL or mode in (2, 4):
                continue
            if kind in self.subgraphs:
                inner = self.inner_graph(graph, node)
                self.note_promoted(graph, node, inner)
                self.walk(inner)
                continue
            if kind not in self.info:
                raise ConvertError(f"node {graph.flat_id(node['id'])} is of type {kind}, which this ComfyUI lacks")
            inputs = self.widget_values(node)
            for entry in node.get("inputs", []):
                source = self.resolve(graph, entry.get("link"))
                if source is None:
                    continue
                if source[0] == "value":
                    inputs[entry["name"]] = source[1]
                else:
                    inputs[entry["name"]] = [source[1], source[2]]
            self.prompt[graph.flat_id(node["id"])] = {
                "class_type": kind,
                "inputs": inputs,
                "_meta": {"title": node.get("title") or kind},
            }

    def note_promoted(self, graph, instance, inner):
        """The settings shown on a subgraph's node: where each one ends up inside, named by its label.

        Only for subgraphs at the top: the miner sets what a person would set in the editor."""
        if graph.prefix:
            return
        definition = inner.definition
        for index, sub_input in enumerate(definition.get("inputs", [])):
            label = sub_input.get("label") or sub_input["name"]
            for link_id in sub_input.get("linkIds", []):
                link = inner.links.get(link_id)
                if link is None:
                    continue
                target, tslot = link[2], link[3]
                node = inner.nodes.get(target)
                if node is None or tslot >= len(node.get("inputs", [])):
                    continue
                self.params.setdefault(label, []).append([inner.flat_id(target), node["inputs"][tslot]["name"]])


def convert(workflow, object_info):
    converter = Converter(workflow, object_info)
    prompt = converter.convert()
    # Inputs fed by a promoted widget of the subgraph: the instance has no value of its own, so the inner node's
    # widget value stands (it is what the editor shows)
    return prompt, converter.params


def main():
    if len(sys.argv) != 4:
        print("usage: convert.py <template.json> <object_info.json> <out.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1], encoding="utf-8") as f:
        workflow = json.load(f)
    with open(sys.argv[2], encoding="utf-8") as f:
        info = json.load(f)
    prompt, params = convert(workflow, info)
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        json.dump({"prompt": prompt, "params": params}, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
