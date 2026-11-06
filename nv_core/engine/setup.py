"""Game setup (rulebook: Game setup; Revealing input parameters for the Specialty Input Parameters)."""

from nv_core.engine.context import Ctx, build_input_deck, build_probe_deck
from nv_core.settings import Settings
from nv_core.state import GameState, Pending, Probe, Researcher
from nv_core.world_data import WorldData


def specialty_parameters(world: WorldData, probe_index: int) -> list[str]:
    """The Probe's Specialty Input Parameters (Revealing input parameters)."""
    ids = world.input_ids
    if len(ids) == 1:
        return [ids[0]]
    return [ids[0], ids[1 + probe_index % (len(ids) - 1)]]


def build_period_deck(ctx: Ctx, n_players: int) -> str:
    s = ctx.settings
    crisis_part = list("c" * (s.calm_cards_per_player_crisis * n_players) + "x")
    warning_part = list("c" * (s.calm_cards_per_player_warning * n_players) + "w")
    ctx.rng.shuffle("setup", crisis_part)
    ctx.rng.shuffle("setup", warning_part)
    top = "c" * (s.calm_cards_per_player_top * n_players)
    return top + "".join(warning_part) + "".join(crisis_part)


def create_game(world: WorldData, settings: Settings, seed: int, players: list[str]) -> GameState:
    """The state after Game setup, before the first decision."""
    n = len(players)
    if not settings.min_players <= n <= settings.max_players:
        raise ValueError(f"{n} players: the game needs {settings.min_players}-{settings.max_players} (min/max_players)")
    if len(set(players)) != n:
        raise ValueError("player names must be different")
    state = GameState(world=world, settings=settings, seed=seed, players=list(players))
    ctx = Ctx(state)
    state.period_deck = build_period_deck(ctx, n)
    state.hot_topic = 0
    state.probes = [Probe(index=i, specialty=specialty_parameters(world, i)) for i in range(n + 1)]
    state.probe_deck = build_probe_deck(ctx)
    ctx.rng.shuffle("probe_deck", state.probe_deck)
    for parameter in world.input_ids:
        deck = build_input_deck(ctx, parameter)
        ctx.rng.shuffle("input_decks", deck)
        state.input_decks[parameter] = deck
        state.input_discards[parameter] = []
    state.first_player = ctx.rng.randint("setup", 0, n - 1)
    start = settings.grant_track_starting_position
    state.researchers = [
        Researcher(
            seat=seat,
            name=name,
            credit=settings.starting_academic_credit,
            money=settings.grant_track[start - 1].funding,
            grant_position=start,
            talent_position=settings.talent_development_track_starting_position,
        )
        for seat, name in enumerate(players)
    ]
    state.pending = [Pending() for _ in players]
    return state
