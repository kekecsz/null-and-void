"""The scenario and World Table data the rules engine plays with.

``nv_core`` may not import ``nv_world`` (specification section 3), so the world generator's
scenario and world file are converted into this plain model (``nv_world.game.world_data``).
"""

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Variable(_Frozen):
    """An input parameter or a world outcome, in World Grid row order."""

    id: str
    name: str
    states: list[str]


class WorldRow(_Frozen):
    """One row of the World Table: an input combination and its realised outcomes."""

    inputs: dict[str, str]
    outcomes: dict[str, str]


class WorldData(_Frozen):
    scenario_id: str
    title: str
    story: str
    world_id: str
    input_parameters: list[Variable]
    world_outcomes: list[Variable]
    rows: list[WorldRow]

    @property
    def variables(self) -> list[Variable]:
        return [*self.input_parameters, *self.world_outcomes]

    @property
    def input_ids(self) -> list[str]:
        return [v.id for v in self.input_parameters]

    @property
    def outcome_ids(self) -> list[str]:
        return [v.id for v in self.world_outcomes]

    def variable(self, variable_id: str) -> Variable:
        for variable in self.variables:
            if variable.id == variable_id:
                return variable
        raise KeyError(variable_id)

    def outcomes_for(self, inputs: dict[str, str]) -> dict[str, str]:
        """The realised world outcomes for a complete input combination."""
        for row in self.rows:
            if row.inputs == inputs:
                return dict(row.outcomes)
        raise KeyError(f"no World Table row for {inputs}")
