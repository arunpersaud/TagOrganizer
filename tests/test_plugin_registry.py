"""The registry the menu, the auto-run chain and the settings page share.

Three hand-maintained lists drifting apart is the problem this replaces, so
ordering and grouping are asserted rather than assumed.
"""

import pytest

from tagorganizer.plugins import Plugin, Registry


class Alpha(Plugin):
    name = "Alpha"
    category = "Maintenance"

    def run(self, ctx):
        yield 1, 1


class Beta(Plugin):
    name = "Beta"
    category = "Tags"
    auto = True

    def run(self, ctx):
        yield 1, 1


class TestRegistry:
    def test_registration_order_is_preserved(self):
        """Menu order must be stable between runs."""
        registry = Registry()
        registry.add(Alpha())
        registry.add(Beta())
        assert [p.name for p in registry.all()] == ["Alpha", "Beta"]

    def test_groups_by_category_in_first_seen_order(self):
        registry = Registry()
        registry.add(Alpha())
        registry.add(Beta())
        grouped = registry.by_category()
        assert list(grouped) == ["Maintenance", "Tags"]
        assert [p.name for p in grouped["Maintenance"]] == ["Alpha"]

    def test_plugins_sharing_a_category_stay_together(self):
        class Gamma(Plugin):
            name = "Gamma"
            category = "Maintenance"

            def run(self, ctx):
                yield 1, 1

        registry = Registry()
        registry.add(Alpha())
        registry.add(Beta())
        registry.add(Gamma())
        grouped = registry.by_category()
        assert [p.name for p in grouped["Maintenance"]] == ["Alpha", "Gamma"]

    def test_auto_plugins_are_the_ones_marked_auto(self):
        registry = Registry()
        registry.add(Alpha())
        registry.add(Beta())
        assert [p.name for p in registry.auto_plugins()] == ["Beta"]

    def test_a_plugin_without_a_name_is_refused(self):
        """An unnamed plugin would appear as a blank menu entry."""

        class Nameless(Plugin):
            def run(self, ctx):
                yield 1, 1

        with pytest.raises(ValueError, match="name"):
            Registry().add(Nameless())

    def test_the_refusal_says_which_class_is_at_fault(self):
        class AlsoNameless(Plugin):
            def run(self, ctx):
                yield 1, 1

        with pytest.raises(ValueError, match="AlsoNameless"):
            Registry().add(AlsoNameless())

    def test_all_returns_a_copy(self):
        """Callers must not be able to reorder the registry by accident."""
        registry = Registry()
        registry.add(Alpha())
        registry.all().clear()
        assert len(registry.all()) == 1


class TestDefaults:
    def test_a_plugin_accepts_a_selection_by_default(self):
        assert Alpha().accepts_selection is True

    def test_a_plugin_does_not_auto_run_by_default(self):
        assert Alpha().auto is False

    def test_the_default_category_is_tasks(self):
        class Bare(Plugin):
            name = "Bare"

            def run(self, ctx):
                yield 1, 1

        assert Bare().category == "Tasks"

    def test_the_base_class_refuses_to_run(self):
        """Plugin is an interface; forgetting run must not fail silently."""
        with pytest.raises(NotImplementedError):
            Plugin().run(None)


class TestDisablingPlugins:
    """A disabled plugin stays known but stops appearing anywhere.

    It has to stay in the registry: the settings window lists it so it can be
    switched back on, which is impossible if loading dropped it.
    """

    def _registry(self):
        registry = Registry()
        registry.add(Alpha())
        registry.add(Beta())
        return registry

    def test_a_disabled_plugin_is_not_offered(self):
        registry = self._registry()
        registry.set_disabled({"Alpha"})
        assert [p.name for p in registry.all()] == ["Beta"]

    def test_a_disabled_plugin_is_not_in_the_menu_groups(self):
        registry = self._registry()
        registry.set_disabled({"Alpha"})
        assert "Maintenance" not in registry.by_category()

    def test_a_disabled_plugin_does_not_run_automatically(self):
        registry = self._registry()
        registry.set_disabled({"Beta"})
        assert registry.auto_plugins() == []

    def test_every_still_lists_it_so_it_can_be_re_enabled(self):
        registry = self._registry()
        registry.set_disabled({"Alpha"})
        assert [p.name for p in registry.every()] == ["Alpha", "Beta"]

    def test_it_reports_which_are_disabled(self):
        registry = self._registry()
        registry.set_disabled({"Alpha"})
        assert registry.is_disabled(Alpha()) is True
        assert registry.is_disabled(Beta()) is False

    def test_enabling_again_brings_it_back(self):
        registry = self._registry()
        registry.set_disabled({"Alpha"})
        registry.set_disabled(set())
        assert [p.name for p in registry.all()] == ["Alpha", "Beta"]

    def test_a_disabled_name_that_matches_nothing_is_harmless(self):
        """A plugin can be uninstalled while still named in the config."""
        registry = self._registry()
        registry.set_disabled({"Gone"})
        assert len(registry.all()) == 2


class TestCategoryOrder:
    """The menu bar reads left to right, so order is not cosmetic."""

    def _registry_with(self, *categories):
        registry = Registry()
        for index, category in enumerate(categories):
            plugin = Alpha()
            plugin.name = f"Plugin {index}"
            plugin.category = category
            registry.add(plugin)
        return registry

    def test_the_common_categories_come_first_in_a_fixed_order(self):
        """Filename order put Maintenance last, which is where the tasks a
        user reaches for most often live."""
        registry = self._registry_with("Reports", "Files", "Maintenance")
        assert list(registry.by_category()) == ["Maintenance", "Files", "Reports"]

    def test_unknown_categories_follow_alphabetically(self):
        registry = self._registry_with("Zebra", "Maintenance", "Apple")
        assert list(registry.by_category()) == ["Maintenance", "Apple", "Zebra"]

    def test_a_plugin_defined_category_is_not_dropped(self):
        registry = self._registry_with("Tags")
        assert list(registry.by_category()) == ["Tags"]
