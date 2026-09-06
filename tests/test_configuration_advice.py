from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from agent_factory.configuration_advice import advise, CATALOG, GIB
from agent_factory.game_planning import template

NOW = datetime(2026,9,6,12,tzinfo=timezone.utc)
def report(total=16, available=8, disk=20, vram=8):
    return {"observed_at": NOW.isoformat(), "os":{"name":"Windows","release":"11"},
            "memory":{"total_bytes":total*GIB,"available_bytes":available*GIB},
            "disk":{"free_bytes":disk*GIB}, "gpus":[{"dedicated_total_bytes":vram*GIB if vram is not None else None}]}

class ConfigurationAdviceTests(unittest.TestCase):
    def test_capacity_decision_table(self):
        for total,available,disk,vram,expected,local in [
            (4,2,20,None,"manual",False),(8,4,10,None,"godot-cloud",False),
            (16,8,15,8,"godot-local",True),(16,8,15,None,"godot-cloud",True),
            (32,2,50,16,"manual",False),(32,24,1,16,"manual",False),
            (16,8,15,0,"godot-cloud",True)]:
            with self.subTest(total=total,available=available,disk=disk,vram=vram):
                result=advise(template(),report(total,available,disk,vram),now=NOW)
                self.assertEqual(result["recommended"],expected)
                self.assertEqual(result["options"][2]["selectable"],local)
                self.assertFalse(result["execution_ready"])
    def test_unknown_and_stale_never_become_positive_evidence(self):
        for data in ({}, report()|{"observed_at":None}, report()|{"observed_at":(NOW-timedelta(minutes=16)).isoformat()},
                     report()|{"observed_at":(NOW+timedelta(seconds=1)).isoformat()},report()|{"observed_at":"2026-09-06T12:00:00"},
                     report()|{"os":{"name":"Mystery"}},report()|{"os":{"name":"Windows","release":"7"}}):
            with self.subTest(data=data):
                result=advise(template(),data,now=NOW)
                self.assertEqual(result["recommended"],"manual");self.assertFalse(result["options"][2]["selectable"])
    def test_catalog_expiry_requires_review_and_does_not_switch_idea(self):
        result=advise(template(),report(),now=NOW+timedelta(days=31))
        self.assertFalse(result["catalog_current"]);self.assertFalse(result["options"][1]["selectable"])
        fields=template()|{"engine":"unreal","deferred_scope":"Large persistent city"}
        before=deepcopy(fields);result=advise(fields,report(),now=NOW)
        self.assertEqual(fields,before);self.assertEqual(result["recommended"],"manual")
        self.assertEqual(result["options"][0]["engine"],"unreal")
    def test_web_target_and_unknown_gpu_have_explicit_limits(self):
        result=advise(template()|{"platform":"web"},report(vram=None),now=NOW)
        self.assertIn("браузері",result["target"])
        self.assertTrue(any("Пам’ять відеокарти невідома" in reason for reason in result["reasons"]))
        self.assertFalse(result["options"][3]["selectable"])
    def test_invalid_numeric_and_nested_data_rejected(self):
        for bad in (-1,True,"99999999",float('nan'),2**61):
            data=report();data["memory"]["total_bytes"]=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):advise(template(),data,now=NOW)
        for changes in ({"memory":[]},{"gpus":[1]},{"gpus":[{}]*17},{"memory":{"total_bytes":1,"available_bytes":2}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):advise(template(),report()|changes,now=NOW)
    def test_digest_binds_plan_and_observation_without_echoing_private_text(self):
        fields=template()|{"goal":"private-canary"}; data=report(); before=deepcopy(data)
        one=advise(fields,data,now=NOW);two=advise(fields|{"goal":"other"},data,now=NOW)
        self.assertNotEqual(one["input_digest"],two["input_digest"])
        self.assertNotIn("private-canary",str(one));self.assertEqual(data,before)
        self.assertEqual(one["observation_trust"],"client_reported_planning_only")
        self.assertEqual(one["catalog"]["reviewed_on"],"2026-09-06")
        one["catalog"]["sources"].clear();self.assertTrue(CATALOG["sources"])
