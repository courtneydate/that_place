"""SR-08 — JSONPath library security test.

Verifies that the project uses the core `jsonpath_ng` parser (no eval extensions)
and that filter expressions containing arbitrary comparisons cannot be evaluated.

The `.ext` module of jsonpath_ng adds filter expressions (`?(@.field > value)`)
and arithmetic that expand the attack surface for a compromised That Place Admin
account. The core module supports only standard path navigation.

Ref: security_risks.md § SR-08
"""
import pytest


class TestJsonPathLibrarySecurity:
    """The core jsonpath_ng parser must be used — not the ext variant."""

    def test_simple_path_parses_and_matches(self):
        """Standard dotted paths work correctly with the core parser."""
        from jsonpath_ng import parse
        expr = parse('$.PRICE')
        matches = expr.find({'PRICE': 42.5})
        assert len(matches) == 1
        assert matches[0].value == 42.5

    def test_array_wildcard_parses_and_matches(self):
        """Array wildcard expressions work correctly with the core parser."""
        from jsonpath_ng import parse
        expr = parse('$.results[*].id')
        matches = expr.find({'results': [{'id': 1}, {'id': 2}]})
        assert [m.value for m in matches] == [1, 2]

    def test_nested_array_iteration_matches(self):
        """The AEMO-style expression used in production works with the core parser."""
        from jsonpath_ng import parse
        expr = parse('$.ELEC_NEM_SUMMARY[*]')
        data = {'ELEC_NEM_SUMMARY': [{'REGIONID': 'NSW1', 'PRICE': 100.0}]}
        matches = expr.find(data)
        assert len(matches) == 1
        assert matches[0].value['REGIONID'] == 'NSW1'

    def test_filter_expression_raises_parse_error(self):
        """Filter expressions must NOT be parseable — confirms ext module is not in use.

        If this test fails, the codebase has been switched back to jsonpath_ng.ext,
        which allows arbitrary filter evaluation from DB-stored config.
        """
        from jsonpath_ng import parse
        with pytest.raises(Exception):
            parse('$.items[?(@.price > 100)]')

    def test_arithmetic_expression_raises_parse_error(self):
        """Arithmetic filter expressions must NOT be parseable."""
        from jsonpath_ng import parse
        with pytest.raises(Exception):
            parse('$.items[?(@.qty * @.price > 500)]')

    def test_ext_module_is_not_imported_in_feeds_tasks(self):
        """The feeds tasks module must import from jsonpath_ng, not jsonpath_ng.ext."""
        import importlib
        import inspect
        from apps.feeds import tasks
        source = inspect.getsource(tasks)
        assert 'from jsonpath_ng import parse' in source
        assert 'from jsonpath_ng.ext import parse' not in source

    def test_ext_module_is_not_imported_in_integrations_tasks(self):
        """The integrations tasks module must import from jsonpath_ng, not jsonpath_ng.ext."""
        import inspect
        from apps.integrations import tasks
        source = inspect.getsource(tasks)
        assert 'from jsonpath_ng import parse' in source
        assert 'from jsonpath_ng.ext import parse' not in source

    def test_ext_module_is_not_imported_in_integrations_views(self):
        """The integrations views module must import from jsonpath_ng, not jsonpath_ng.ext."""
        import inspect
        from apps.integrations import views
        source = inspect.getsource(views)
        assert 'from jsonpath_ng import parse' in source
        assert 'from jsonpath_ng.ext import parse' not in source
