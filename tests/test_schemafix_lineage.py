"""Synthetic adversarial tests; real release ZIP lineage is separately verified offline."""
import ast
import unittest
from unittest.mock import patch

from updater import schemafix_lineage as s


def synthetic_base():
    return ('def build(props, name, tools):\n' +
            s.OLD_REQUIRED +
            '            tools.append({"inputSchema": {\n' +
            s.OLD_INPUT_SCHEMA +
            '            })\n').encode()


def synthetic_schemafix(source=None):
    base = synthetic_base() if source is None else source
    value = base.decode()
    return value.replace(s.OLD_REQUIRED, s.NEW_REQUIRED).replace(
        s.OLD_INPUT_SCHEMA, s.NEW_INPUT_SCHEMA).encode()


class SchemafixLineageTests(unittest.TestCase):
    def test_fixture_is_syntactically_valid(self):
        ast.parse(synthetic_base().decode())
        ast.parse(synthetic_schemafix().decode())

    def test_exact_known_schemafix_hunks_pass(self):
        self.assertTrue(s.exact_schemafix(synthetic_base(), synthetic_schemafix()))

    def test_additional_change_denied(self):
        other = synthetic_schemafix() + b'\n# unexpected change\n'
        with self.assertRaisesRegex(s.LineageBlocked,
                                    'SCHEMAFIX_UNEXPECTED_DIFFERENCES'):
            s.exact_schemafix(synthetic_base(), other)

    def test_one_required_line_modified_denied(self):
        tampered = synthetic_base().replace(
            s.OLD_REQUIRED.encode(), b'            required = []\n')
        with self.assertRaisesRegex(s.LineageBlocked, 'SCHEMAFIX_ANCHOR_MISMATCH'):
            s.exact_schemafix(tampered, synthetic_schemafix())

    def test_other_tools_schema_changed_denied(self):
        other = synthetic_schemafix().replace(
            b'"additionalProperties": False', b'"additionalProperties": True')
        with self.assertRaisesRegex(s.LineageBlocked,
                                    'SCHEMAFIX_UNEXPECTED_DIFFERENCES'):
            s.exact_schemafix(synthetic_base(), other)

    def test_repeated_anchor_denied(self):
        duplicated = synthetic_base() + s.OLD_REQUIRED.encode()
        with self.assertRaisesRegex(s.LineageBlocked, 'SCHEMAFIX_ANCHOR_MISMATCH'):
            s.exact_schemafix(duplicated, synthetic_schemafix())

    def test_unknown_base_hash_denied_before_overlay(self):
        base = synthetic_base()
        other = synthetic_schemafix()
        with self.assertRaisesRegex(s.LineageBlocked, 'BASE_HASH_MISMATCH'):
            s.audit(base=base, schemafix=other, async_r2=base)

    def test_schemafix_hash_denied_before_overlay(self):
        base = synthetic_base()
        with patch.object(s, 'BASE_SHA', s.sha(base)):
            with self.assertRaisesRegex(s.LineageBlocked, 'SCHEMAFIX_HASH_MISMATCH'):
                s.audit(base=base, schemafix=synthetic_schemafix(), async_r2=base)

    def test_async_r2_hash_denied_before_overlay(self):
        base = synthetic_base()
        fixed = synthetic_schemafix()
        with patch.object(s, 'BASE_SHA', s.sha(base)), \
             patch.object(s, 'SCHEMAFIX_SHA', s.sha(fixed)):
            with self.assertRaisesRegex(s.LineageBlocked, 'ASYNC_R2_HASH_MISMATCH'):
                s.audit(base=base, schemafix=fixed, async_r2=base)

    def test_no_secret_or_raw_source_exposed_in_success_result_schema(self):
        result = {
            'status': 'OFFLINE_SCHEMAFIX_LINEAGE_PASS',
            'base_sha256': s.BASE_SHA,
            'schemafix_sha256': s.SCHEMAFIX_SHA,
            'activation_authorized': False,
            'mcp_modified': False,
        }
        self.assertNotIn('source', result)
        self.assertFalse(result['activation_authorized'])

    def test_source_limit_and_bad_syntax_denied(self):
        with self.assertRaisesRegex(s.LineageBlocked, 'SOURCE_SIZE_OR_TYPE_DENIED'):
            s.exact_schemafix(b'x' * (s.MAX_SOURCE + 1), b'data')
        with self.assertRaisesRegex(s.LineageBlocked, 'SOURCE_INVALID_PYTHON'):
            s.exact_schemafix(b'def broken(:\n', b'x=1\n')


if __name__ == '__main__':
    unittest.main()
