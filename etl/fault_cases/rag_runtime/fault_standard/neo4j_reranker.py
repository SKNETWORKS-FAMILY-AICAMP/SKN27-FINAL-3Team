"""Neo4j Reranker for Complete30 V9."""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

from .utils import normalize_signal

BUCKET = {"GRAPH_FULL_MATCH": 0, "FULL_MATCH": 1, "FLAT_FULL_GRAPH_INELIGIBLE": 1,
          "AMBIGUOUS_PARTY": 1, "GRAPH_COMPATIBLE_UNKNOWN": 2,
          "COMPATIBLE_UNKNOWN": 2, "UNMODELED": 3, "MISMATCH": 4, "GRAPH_MISMATCH": 4}

def evaluate_rule(rule_id: str, conditions: list[dict[str, Any]], facts: dict[str, str]) -> dict[str, Any]:
    if not conditions:
        return {"rule_id": rule_id, "state": "UNMODELED", "mapping": None, "trace": [], "missing": []}
    party_keys = sorted({str(item["subject_party_key"]) for item in conditions if item.get("subject_party_key")})
    if len(party_keys) != 2:
        return {"rule_id": rule_id, "state": "UNMODELED", "mapping": None, "trace": [], "missing": []}
    mapping_results = []
    for ordered in itertools.permutations(party_keys, 2):
        mapping = {"user": ordered[0], "opponent": ordered[1]}
        inverse = {value: key for key, value in mapping.items()}
        trace, missing, mismatch = [], [], False
        for condition in conditions:
            subject = condition["subject_party_key"]
            scope = inverse.get(subject, "scene") if subject else "scene"
            fact_key = f"{scope}.{condition['fact_key']}"
            actual = facts.get(fact_key, "unknown")
            expected = str(condition["expected_value"])
            state = "UNKNOWN" if actual == "unknown" else "MATCH" if actual == expected else "MISMATCH"
            trace.append({"condition_id": condition["condition_id"], "subject_party_key": subject, "fact_key": fact_key, "expected_value": expected, "actual_value": actual, "state": state})
            if state == "UNKNOWN":
                missing.append(fact_key)
            if state == "MISMATCH":
                mismatch = True
        mapping_results.append({"mapping": mapping, "state": "MISMATCH" if mismatch else "COMPATIBLE_UNKNOWN" if missing else "FULL_MATCH", "missing": sorted(set(missing)), "trace": trace})
    full = [item for item in mapping_results if item["state"] == "FULL_MATCH"]
    if len(full) == 1:
        return {"rule_id": rule_id, "state": "FULL_MATCH", "mapping": full[0]["mapping"], "trace": full[0]["trace"], "missing": []}
    if len(full) > 1:
        return {"rule_id": rule_id, "state": "AMBIGUOUS_PARTY", "mapping": None, "trace": [trace for item in full for trace in item["trace"]], "missing": []}
    unknown = [item for item in mapping_results if item["state"] == "COMPATIBLE_UNKNOWN"]
    if unknown:
        return {"rule_id": rule_id, "state": "COMPATIBLE_UNKNOWN", "mapping": None, "trace": [trace for item in unknown for trace in item["trace"]], "missing": sorted({fact for item in unknown for fact in item["missing"]})}
    return {"rule_id": rule_id, "state": "MISMATCH", "mapping": None, "trace": [trace for item in mapping_results for trace in item["trace"]], "missing": []}

def _flat_for_mapping(conditions: list[dict[str, Any]], mapping: dict[str, str], facts: dict[str, str]) -> tuple[str, list[dict[str, Any]], list[str]]:
    inverse={v:k for k,v in mapping.items()}; trace=[]; missing=[]; mismatch=False
    for condition in conditions:
        subject=condition.get("subject_party_key"); scope=inverse.get(subject,"scene") if subject else "scene"; key=f"{scope}.{condition['fact_key']}"; actual=facts.get(key,"unknown"); expected=str(condition["expected_value"]); state="UNKNOWN" if actual=="unknown" else "MATCH" if actual==expected else "MISMATCH"
        trace.append({"condition_id":condition["condition_id"],"subject_party_key":subject,"fact_key":key,"expected_value":expected,"actual_value":actual,"state":state}); missing += [key] if state=="UNKNOWN" else []; mismatch |= state=="MISMATCH"
    return ("MISMATCH" if mismatch else "COMPATIBLE_UNKNOWN" if missing else "FULL_MATCH"),trace,sorted(set(missing))

def _graph_for_mapping(mapping: dict[str, str], graph: dict[str, Any], facts: dict[str, str]) -> dict[str, Any]:
    inverse = {v: k for k, v in mapping.items()}
    trace: list[dict[str, Any]] = []; missing: list[str] = []; mismatch = False; eligible = False
    step_field = {"진입": "entry_lane", "회전": "circulation_lane", "진출": "exit_lane"}
    direction_field = {"진입": "entry_direction", "진출": "exit_direction"}
    for party, steps in graph["steps"].items():
        scope = inverse.get(party)
        if not scope: continue
        previous = None
        for step in steps:
            movement, lane, direction = str(step.get("movement") or ""), step.get("lane"), step.get("direction")
            if previous is not None:
                trace.append({"relation":"NEXT_STEP","party_key":party,"from_seq":previous.get("seq"),"to_seq":step.get("seq"),"state":"TRACE","source":"lane_steps.seq"})
            previous = step
            field = step_field.get(movement)
            if field and lane:
                key, actual = f"{scope}.{field}", facts.get(f"{scope}.{field}", "unknown")
                state = "UNKNOWN" if actual == "unknown" else "MATCH" if actual == str(lane).replace(" ", "") else "MISMATCH"
                trace.append({"relation":"LanePath-HAS_STEP","party_key":party,"seq":step.get("seq"),"fact_key":key,"expected_value":str(lane).replace(" ", ""),"actual_value":actual,"state":state,"source":"lane_steps"})
                eligible = True; missing += [key] if state == "UNKNOWN" else []; mismatch |= state == "MISMATCH"
            dfield = direction_field.get(movement)
            if dfield and direction:
                key, actual = f"{scope}.{dfield}", facts.get(f"{scope}.{dfield}", "unknown")
                state = "UNKNOWN" if actual == "unknown" else "MATCH" if actual == str(direction) else "MISMATCH"
                trace.append({"relation":"LaneStep.direction","party_key":party,"seq":step.get("seq"),"fact_key":key,"expected_value":str(direction),"actual_value":actual,"state":state,"source":"lane_steps"})
                eligible = True; missing += [key] if state == "UNKNOWN" else []; mismatch |= state == "MISMATCH"
    party_type = {x.get("party_key"): x.get("party_type") for x in graph["parties"]}
    for context in graph["contexts"]:
        if context.get("rule_id") is None: continue
        for field, typ in (("pm_signal_state", "pm"), ("car_signal_state", "vehicle")):
            expected = normalize_signal(context.get(field))
            parties = [p for p, value in party_type.items() if value == typ]
            if not expected or len(parties) != 1 or parties[0] not in inverse: continue
            key, actual = f"{inverse[parties[0]]}.signal_state", facts.get(f"{inverse[parties[0]]}.signal_state", "unknown")
            state = "UNKNOWN" if actual == "unknown" else "MATCH" if actual == expected else "MISMATCH"
            trace.append({"relation":"Rule-HAS_CONTEXT","context_table":context.get("rule_id"),"fact_key":key,"expected_value":expected,"actual_value":actual,"state":state})
            eligible = True; missing += [key] if state == "UNKNOWN" else []; mismatch |= state == "MISMATCH"
    for edge in graph["precedence"]:
        trace.append({"relation":"PRECEDES_ENTRY","first_party":edge["first"],"late_party":edge["late"],"state":"SOURCE_TRACE_ONLY"})
    for item in graph["potential_conflicts"]:
        trace.append({"relation":"POTENTIALLY_CONVERGES_ON","party_key":item["party"],"lane":item["lane"],"state":"DERIVED_TRACE_ONLY","not_collision_fact":True})
    for variant in graph["variants"]:
        trace.append({"relation":"HAS_VARIANT","variant_id":variant.get("variant_id"),"state":"SOURCE_TRACE_ONLY"})
    if mismatch: state = "GRAPH_MISMATCH"
    elif not eligible: state = "FLAT_FULL_GRAPH_INELIGIBLE"
    elif missing: state = "GRAPH_COMPATIBLE_UNKNOWN"
    else: state = "GRAPH_FULL_MATCH"
    return {"state":state,"mapping":mapping,"trace":trace,"missing":sorted(set(missing)),"eligible":eligible}

def graph_relation_status(base: dict[str, Any], graph: dict[str, Any], facts: dict[str, str]) -> dict[str, Any]:
    party_keys=sorted({str(x.get("party_key")) for x in graph["parties"] if x.get("party_key")})
    if len(party_keys)!=2 or not graph["conditions"]:
        return {"state":base["state"],"mapping":base.get("mapping"),"trace":[],"missing":base.get("missing",[]),"eligible":False,"flat_trace":base.get("trace",[])}
    candidates=[]
    for ordered in itertools.permutations(party_keys,2):
        mapping={"user":ordered[0],"opponent":ordered[1]}; flat_state,flat_trace,flat_missing=_flat_for_mapping(graph["conditions"],mapping,facts)
        if flat_state=="MISMATCH":
            candidates.append({"flat_state":flat_state,"state":"MISMATCH","mapping":mapping,"flat_trace":flat_trace,"trace":[],"missing":flat_missing,"eligible":False}); continue
        related=_graph_for_mapping(mapping,graph,facts)
        candidates.append({"flat_state":flat_state,"flat_trace":flat_trace,**related})
    full=[x for x in candidates if x["state"]=="GRAPH_FULL_MATCH"]
    if len(full)==1: return full[0]
    if len(full)>1: return {"state":"AMBIGUOUS_PARTY","mapping":None,"trace":[y for x in full for y in x["trace"]],"missing":[],"eligible":True,"flat_trace":[y for x in full for y in x["flat_trace"]]}
    unknown=[x for x in candidates if x["state"]=="GRAPH_COMPATIBLE_UNKNOWN"]
    if unknown and base["state"] == "FULL_MATCH":
        return {"state":"GRAPH_COMPATIBLE_UNKNOWN","mapping":None,"trace":[y for x in unknown for y in x["trace"]],"missing":sorted({y for x in unknown for y in x["missing"]}),"eligible":True,"flat_trace":[y for x in unknown for y in x["flat_trace"]]}
    return {"state":base["state"],"mapping":base.get("mapping"),"trace":[],"missing":base.get("missing",[]),"eligible":False,"flat_trace":base.get("trace",[])}

def select(case_id: str, candidates: list[dict[str, Any]], graphs: dict[str, dict[str, Any]], facts: dict[str, str]) -> dict[str, Any]:
    trace=[]
    for c in candidates:
        graph=graphs[c["rule_id"]]; base=evaluate_rule(c["rule_id"],graph["conditions"],facts); rel=graph_relation_status(base,graph,facts)
        trace.append({"rule_id":c["rule_id"],"original_rank":c["rank"],"cosine_similarity":c["cosine_similarity"],"flat_state":base["state"],"state":rel["state"],"mapping":rel["mapping"],"flat_trace":rel.get("flat_trace",[]),"graph_trace":rel["trace"],"missing":rel["missing"],"graph_eligible":rel["eligible"],"rule_groups":graph["groups"]})
    semantic_top=min(trace,key=lambda x:x["original_rank"])
    ranked=trace if semantic_top["state"] == "GRAPH_COMPATIBLE_UNKNOWN" else sorted(trace,key=lambda x:(BUCKET[x["state"]],x["original_rank"]))
    top=ranked[0]
    mapping=None if top["state"] == "GRAPH_COMPATIBLE_UNKNOWN" else top["mapping"]
    return {"case_id":case_id,"method":"C2B","selected_rule_id":top["rule_id"],"party_mapping":mapping,"selection_state":top["state"],"ranked_rule_ids":[x["rule_id"] for x in ranked],"state_counts":dict(Counter(x["state"] for x in trace)),"decision_trace":trace}

def calculator_profiles(selected: list[dict[str, Any]], graphs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    needed={x["selected_rule_id"] for x in selected}
    return {rid:{"rule_id":rid,"source_records":{"base_faults":graphs[rid]["bases"],"parties":graphs[rid]["parties"],"adjustment_factors":graphs[rid]["adjustments"]}} for rid in needed}
