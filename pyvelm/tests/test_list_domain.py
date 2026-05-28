"""Static ``arch["domain"]`` on list views."""

import unittest

from pyvelm import BaseModel, Boolean, Char
from pyvelm.registry import Registry
from pyvelm.render import _list_page_domain


class ListArchDomainTests(unittest.TestCase):
    def test_list_page_domain_merges_arch_search_and_filters(self):
        reg = Registry()
        with reg.activate():

            class Thing(BaseModel):
                _name = "test.list_domain.thing"
                name = Char()
                active = Boolean()

        model_cls = reg["test.list_domain.thing"]
        arch = {
            "fields": ["name", "active"],
            "domain": [("active", "=", True)],
        }
        domain = _list_page_domain(model_cls, arch, arch["fields"], "", "")
        self.assertEqual(domain, [("active", "=", True)])

        fields_spec = [{"name": "name"}, {"name": "active"}]
        domain_q = _list_page_domain(model_cls, arch, fields_spec, "acme", "")
        self.assertIn(("active", "=", True), domain_q)
        self.assertGreater(len(domain_q), 1)


if __name__ == "__main__":
    unittest.main()
