"""Small synthetic fixtures only; never opens the CMS database or runs the site build."""
from pathlib import Path
import runpy
import unittest

helpers = runpy.run_path(str(Path(__file__).with_name("site_tables.py")))
changes_for, make_catalog = helpers["changes_for"], helpers["make_catalog"]


class PublicTables(unittest.TestCase):
    def setUp(self):
        self.files = [{"ds": "Hospice Enrollments", "rel": d} for d in ("2024-01-01", "2024-04-01", "2024-07-01")]
        self.files += [{"ds": "Hospice All Owners", "rel": d} for d in ("2024-01-01", "2024-07-01")]
        self.files += [{"ds": "Revoked Medicare Providers and Suppliers", "rel": "2024-10-01"}]
        self.enr = {
            "O1": {"id": "O1", "name": "A CARE", "kind": "hospice", "state": "CA", "status": "active", "ef": [0, 1, 2], "paid": 50, "carrier": ["never publish"], "phone": "5551234567", "official_phone": "never publish"},
            "O2": {"id": "O2", "name": "B CARE", "kind": "hospice", "state": "CA", "status": "revoked", "ef": [1], "paid": 20, "rev_date": "2024-05-02"}}
        self.names = {"I1": "FIRST PERSON", "O9": "COMPANY", "a1": "1 MAIN ST", "a2": "2 MAIN ST"}
        self.links = {
            ("I1", "O1"): {"recs": {("0001", "34", "OWNER", None, None, "FIRST PERSON"): [3]}},
            ("O9", "O1"): {"recs": {("0009", "43", "CONTROL", None, None, "COMPANY"): [4]}},
            ("a1", "O1"): {"recs": {"1 MAIN ST SUITE a": [0, 1]}},
            ("a2", "O1"): {"recs": {"2 MAIN ST SUITE b": [2]}}}

    def test_dataset_calendars_and_gaps(self):
        events = changes_for(self.enr, self.links, self.files, self.names)
        added = next(e for e in events if e["event"] == "Owner/control added")
        self.assertEqual((added["before"], added["release"]), ("2024-01-01", "2024-07-01"))
        self.assertFalse(any(e["event"].startswith("Owner/control") and e["release"] == "2024-04-01" for e in events))
        self.assertEqual(len([e for e in events if e["event"] == "Owner/control removed"]), 1)
        self.assertTrue(any(e["event"] == "New enrollment" and e["id"] == "O2" for e in events))
        self.assertTrue(any(e["event"] == "Enrollment no longer listed" and e["id"] == "O2" for e in events))
        self.assertTrue(any(e["event"] == "Address moved" and "1 MAIN ST → 2 MAIN ST" == e["detail"] for e in events))
        rev = next(e for e in events if e["event"] == "Revocation")
        self.assertEqual(rev["release"], "2024-10-01")
        self.assertIn("Effective 2024-05-02", rev["detail"])

    def test_catalog_whitelist_and_all_enrollments(self):
        graph = {"enr": self.enr, "links": self.links, "names": self.names, "LATEST": "2024-07-01",
                 "addr_enr": {"a1": {"O1", "O2"}}, "addr_links": {
                     ("a1", "O1"): {"recs": {"1 MAIN ST SUITE a": [0, 1]}},
                     ("a1", "O2"): {"recs": {"1 MAIN ST STE B": [1]}}},
                 "MULTITENANT": {"1": {"what": "checked"}}, "virt_addr": {"a1"}, "bldg": {}}
        result = make_catalog(graph, self.files, {"O1": 1, "O2": "solo-O2"})
        self.assertEqual(len(result["agencies"]), 2)
        self.assertIsNone(result["agencies"][1]["group"])
        self.assertFalse(any("ind" in n for n in result["agencies"]))
        ind = {"agencies": {"123456": {"k": "hospice", "ind": ["new_biller"], "m": {}}}, "metrics": {}, "indicators": {"new_biller": {}}}
        self.enr["O1"]["ccn"] = "123456"
        result = make_catalog(graph, self.files, {"O1": 1, "O2": "solo-O2"}, ind)
        self.assertEqual(result["tables"]["indicator_counts"], {"new_biller": 1})
        self.assertFalse(any("ind" in n for n in result["agencies"]))
        self.assertFalse(any("carrier" in n or "official_phone" in n or "phone" in n for n in result["agencies"]))
        address = result["addresses"][0]
        self.assertEqual((address["ever"], address["current"], address["revoked"], address["paid"]), (2, 0, 1, 70))
        self.assertEqual(address["flags"], ["Multi-tenant checked", "Executive suite"])
        listings = result["a/" + address["id"]]
        self.assertEqual(listings[1]["address"], "1 MAIN ST STE B")
        self.assertEqual(result["agencies-first"], result["agencies"])

    def test_public_records_and_reasons(self):
        rows = helpers["public_records"]([{"f": [1], "aid": "9", "nm": "A B", "role": "OWNER", "assoc": "2024-01-01"},
                                          {"f": [2], "aid": "7", "nm": "A B", "role": "OWNER", "assoc": "2024-01-01"}])
        self.assertEqual(rows, [{"role": "OWNER", "assoc": "2024-01-01", "f": [1, 2]}])
        reason = helpers["public_reason"]("42 CFR 424.535(a)(8) abuse of billing privileges; 424.535(a)(3) Felony conviction; 424.535(a)(2) excluded; (a)(19) affiliation")
        self.assertEqual(reason, "42 CFR 424.535(a)(8) abuse of billing privileges; Other grounds; see the CMS record; (a)(19) affiliation")
        # Same vectors as site/test_logic.js: the browser must find the same shard.
        self.assertEqual([helpers["shard_key"](x) for x in ("1", "solo-O2021", "abc", "0f3a")], ["1c", "81", "0b", "cb"])


if __name__ == "__main__":
    unittest.main()
