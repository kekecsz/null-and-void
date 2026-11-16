"""The rulebook's pictures of the game's screens (nv_rulebook.illustrations). Taking the screenshots
needs a browser, so these tests check what comes before: every picture has a scene, and the bot
game has every situation."""

from nv_core.markdown_text import read_markdown
from nv_core.paths import RULEBOOK
from nv_rulebook.illustrations import SCENES, add_sensors, fill_portal, find_situations, near_nobel_and_retraction
from nv_rulebook.pdf import IMAGES, blocks

RULEBOOK_PICTURES = [item for kind, item in blocks(read_markdown(RULEBOOK)) if kind == "figure"]


def test_every_scene_is_a_picture_of_the_rulebook():
    assert [s.name for s in SCENES if f"{s.name}.png" not in RULEBOOK_PICTURES] == []


def test_every_screenshot_in_the_rulebook_has_a_scene():
    """A .png the rulebook asks for is either a scene or a picture kept by hand in web/images."""
    scenes = {f"{s.name}.png" for s in SCENES}
    assert [n for n in RULEBOOK_PICTURES if n not in scenes and not (IMAGES / n).is_file()] == []


def test_the_bot_game_has_every_situation_and_the_adjustments_hold():
    found = find_situations(SCENES)
    assert set(found) == {s.name for s in SCENES}

    state, seat = found["world_grid_obs_before_prediction_reveal"]
    state = state.clone()
    add_sensors(state, seat)
    levels = sorted(level for p in state.probes for level in p.sensors.values())
    assert levels == [1, 2, 3]
    assert all(var not in p.specialty and p.readings[var].state for p in state.probes for var in p.sensors)

    state, seat = found["submission_portal_all_three_areas_containing_submissions"]
    state = state.clone()
    fill_portal(state, seat)
    assert {m.area for m in state.manuscripts} == {"review", "revise", "accept"}

    state, seat = found["literature_theory_close_to_nobel_another_close_to_retraction"]
    state = state.clone()
    near_nobel_and_retraction(state, seat)
    s = state.settings
    assert any(p.nobel == s.nobel_condition - 1 for p in state.published)
    assert any(p.retraction == s.retraction_threshold - 1 for p in state.published)
