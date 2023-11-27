"""RoomEnv2 environment compatible with gym.

This is the most complicated room environment so far. It has multiple rooms.
"""
import json
import logging
import os
import random
from copy import deepcopy
from pprint import pprint
from typing import Any

import gymnasium as gym
import matplotlib.pyplot as plt
from IPython.display import clear_output

from ..utils import is_running_notebook
from ..utils import read_json_prod as read_json
from ..utils import sample_max_value_key, seed_everything

logging.basicConfig(
    level=os.environ.get("LOGLEVEL", "INFO").upper(),
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

EPSILON = 1e-3


class Object:
    def __init__(
        self,
        name: str,
        type: str,
        init_probs: dict,
        transition_probs: dict,
        deterministic_init: bool = False,
    ) -> None:
        """The simplest object class. One should inherit this class to make a more
        complex object.

        Args:
            name: e.g., alice, laptop, bed
            type: static, independent, dependent, or agent
            init_probs: initial probabilities of being in a room
            transition_probs: transition probabilities of moving to another room
            deterministic_init: whether to use a deterministic initial distribution

        """
        self.name = name
        self.type = type
        self.init_probs = init_probs
        if abs(sum(self.init_probs.values()) - 1) >= EPSILON:
            raise ValueError(
                f"The sum of the initial probabilities must be 1. "
                f"but it's {sum(self.init_probs.values())}"
            )
        self.transition_probs = transition_probs

        if deterministic_init:
            self.location = sample_max_value_key(self.init_probs)
        else:
            # place an object in one of the rooms when it is created.
            self.location = random.choices(
                list(self.init_probs.keys()),
                weights=list(self.init_probs.values()),
                k=1,
            )[0]

    def __repr__(self) -> str:
        return f"{self.type.title()}Object(name: {self.name}, location: {self.location}"

    def __eq__(self, other) -> bool:
        return (
            self.name == other.name
            and self.type == other.type
            and self.init_probs == other.init_probs
            and self.transition_probs == other.transition_probs
            and self.location == other.location
        )

    def move_with_action(self, action: str, rooms: dict, current_location: str) -> str:
        """Move with action.

        This method is only relevant for independent and agent objects, since they
        are the only ones that move with their will.

        Args:
            action: north, east, south, west, or stay
            rooms: rooms
            current_location: current location

        Returns:
            next_location: next location

        """
        assert action in [
            "north",
            "east",
            "south",
            "west",
            "stay",
        ], f"{action} is not a valid action"
        if action == "north":
            next_location = rooms[current_location].north
        elif action == "east":
            next_location = rooms[current_location].east
        elif action == "south":
            next_location = rooms[current_location].south
        elif action == "west":
            next_location = rooms[current_location].west
        elif action == "stay":
            next_location = current_location

        if next_location != "wall":
            return next_location
        else:  # if the next location is a wall, stay.
            return current_location


class StaticObject(Object):
    def __init__(
        self,
        name: str,
        init_probs: dict,
        transition_probs: dict,
        deterministic_init: bool = False,
    ) -> None:
        """Static object does not move. Once they are initialized, they stay forever.


        Args:
            name: e.g., bed
            init_probs: initial probabilities of being in a room
            transition_probs: just a place holder. It's not gonna be used anyway.
            deterministic_init: whether to use a deterministic initial distribution

        """
        # Static objects are always initialized in a deterministic way.
        super().__init__(
            name, "static", init_probs, transition_probs, deterministic_init
        )
        assert self.transition_probs is None, "Static objects do not move."

    def __repr__(self) -> str:
        return super().__repr__() + ")"


class IndepdentObject(Object):
    def __init__(
        self,
        name: str,
        init_probs: dict,
        transition_probs: dict,
        rooms: dict,
        deterministic_init: bool = False,
    ) -> None:
        """Independent object moves to another room with the attached dependent objects.

        Args:
            name: e.g., alice
            init_probs: initial probabilities of being in a room
            transition_probs: transition probabilities of moving to another room
            rooms: rooms
            deterministic_init: whether to use a deterministic initial distribution

        """
        super().__init__(
            name, "independent", init_probs, transition_probs, deterministic_init
        )
        for key, val in self.transition_probs.items():
            if abs(sum(val.values()) - 1) >= EPSILON:
                raise ValueError(
                    "The sum of the transition probabilities for an independent object "
                    f"must be 1. but it's {sum(val.values())}"
                )
        self.attached = []
        self.rooms = rooms

    def move(self) -> None:
        """Indendent object moves to another room with the attached dependent objects."""
        action = random.choices(
            list(self.transition_probs[self.location].keys()),
            weights=list(self.transition_probs[self.location].values()),
            k=1,
        )[0]

        self.location = self.move_with_action(action, self.rooms, self.location)

        for do in self.attached:
            do.location = self.location
        self.detach()  # detach the attached dependent objects after moving.

    def detach(self) -> None:
        """Detach from the dependent objects."""
        for do in self.attached:
            do.attached = None
        self.attached = []

    def __repr__(self) -> str:
        return super().__repr__() + f", attached: {[do.name for do in self.attached]})"

    def __eq__(self, other) -> bool:
        return (
            self.name == other.name
            and self.type == other.type
            and self.init_probs == other.init_probs
            and self.transition_probs == other.transition_probs
            and self.location == other.location
            and self.attached == other.attached
            and self.rooms == other.rooms
        )


class DependentObject(Object):
    def __init__(
        self,
        name: str,
        init_probs: dict,
        transition_probs: dict,
        independent_objects: list,
        deterministic_init: bool = False,
    ) -> None:
        """Dependent object attaches to an independent object.

        It doesn't have the move method, since it moves with the independent object.

        Args:
            name: e.g., laptop.
            init_probs: initial probabilities of being in a room.
            transition_probs: transition probabilities of moving to another room.
            independent_objects: independent objects in the environment.
            deterministic_init: whether to use a deterministic initial distribution

        """
        super().__init__(
            name, "dependent", init_probs, transition_probs, deterministic_init
        )
        for key, val in self.transition_probs.items():
            if val >= 1 + EPSILON:
                raise ValueError(
                    "The transition probability for a dependent object must "
                    f"be <= 1. but it's {val}"
                )
        self.independent_objects = independent_objects
        self.attach()  # attach to an independent object when it is created.

    def attach(self) -> None:
        """Attach to an independent object, with the provided randomness."""
        self.attached = None
        possible_attachments = []
        for io in self.independent_objects:
            if io.location == self.location:
                for io_name, prob in self.transition_probs.items():
                    if io.name == io_name:
                        if random.random() < prob:
                            possible_attachments.append(io)

        if len(possible_attachments) > 0:
            io = random.choice(possible_attachments)
            self.attached = io
            if self.name not in [do.name for do in io.attached]:
                io.attached.append(self)

    def __repr__(self) -> str:
        if self.attached is None:
            return super().__repr__() + ", attached: None)"
        else:
            return super().__repr__() + f", attached: {self.attached.name})"

    def __eq__(self, other) -> bool:
        return (
            self.name == other.name
            and self.type == other.type
            and self.init_probs == other.init_probs
            and self.transition_probs == other.transition_probs
            and self.location == other.location
            and self.attached == other.attached
            and self.independent_objects == other.independent_objects
        )


class Agent(Object):
    def __init__(
        self,
        name: str,
        init_probs: dict,
        transition_probs: dict,
        rooms: dict,
        deterministic_init: bool = False,
    ) -> None:
        """Agent class is the same as the independent object class, except that it
        moves with the provided action."""
        super().__init__(
            name, "agent", init_probs, transition_probs, deterministic_init
        )
        assert self.transition_probs is None, "Agent objects do not move by itself."
        self.rooms = rooms

    def move(self, action: str) -> None:
        """Agent can move north, east, south. west, or stay."""
        self.location = self.move_with_action(action, self.rooms, self.location)

    def __repr__(self) -> str:
        return "Agent(name: agent, location: " + self.location + ")"

    def __eq__(self, other) -> bool:
        return (
            self.name == other.name
            and self.type == other.type
            and self.init_probs == other.init_probs
            and self.transition_probs == other.transition_probs
            and self.location == other.location
            and self.rooms == other.rooms
        )


class Room:
    def __init__(self, name: str, north: str, east: str, south: str, west: str) -> None:
        """Room. It has four sides and they can be either a wall or another room.

        Args:
            name: e.g., officeroom, livingroom, bedroom
            north, east, south, west: either wall or another room

        """
        self.name = name
        self.north = north
        self.east = east
        self.south = south
        self.west = west

        rooms_walls = [self.north, self.east, self.south, self.west]
        rooms_walls = [rw for rw in rooms_walls if rw != "wall"]
        assert len(set(rooms_walls)) == len(rooms_walls), "room layout wrong."

    def __repr__(self) -> str:
        return (
            f"Room(name: {self.name}, north: {self.north}, east: {self.east}, "
            f"south: {self.south}, west: {self.west})"
        )

    def __eq__(self, other) -> bool:
        return (
            self.name == other.name
            and self.north == other.north
            and self.east == other.east
            and self.south == other.south
            and self.west == other.west
        )


class RoomEnv2(gym.Env):
    """the Room environment version 2.

    This environment is more formalized than the previous environments. Multiple rooms
    are supported. The agent can move north, east, south, west, or stay. Static,
    independent, dependent, agent objects are supported. Static objects do not move.
    Independent objects move with their will. Dependent objects move with independent
    objects. Agent moves with the provided action.

    Every string value is lower-cased to avoid confusion!!!

    """

    def __init__(
        self,
        question_prob: int = 1.0,
        seed: int = 42,
        terminates_at: int = 99,
        randomize_observations: bool = False,
        room_size: str = "dev",
        deterministic_init: bool = False,
    ) -> None:
        """

        Attributes:
            rooms: rooms: dict
            objects: objects: dict of lists
            question: question: list of strings
            answers: answers: list of strings
            current_time: current time: int
            room_config: room configuration
            object_transition_config: object transition configuration
            object_init_config: object initial configuration
            randomize_observations: whether to randomize the order of the observations.

        Args:
            question_prob: The probability of a question being asked at every observation.
            seed: random seed number
            terminates_at: the environment terminates at this time step.
            randomize_observations: whether to randomize the order of the observations.
                If True, the first observation is always the agent's location. and the reset
                is random. If False, the first observation is always the agent's location,
                and the rest is in the order of the hidden global state, i.e., agent, static
                independent, dependent, and rooms.
            room_size: The room configuration to use. Choose one of "dev", "xxs", "xs",
                "s", "m", or "l". You can also pass this argument as a dictionary, if you
                have your pre-configured room configuration.
            deterministic_init: Whether to use a deterministic initial distribution

        """
        super().__init__()
        self.is_notebook = is_running_notebook()
        if isinstance(room_size, str):
            config_all = read_json(f"./data/room-config-{room_size}-v2.json")
        else:
            for key in [
                "object_init_config",
                "object_transition_config",
                "room_config",
            ]:
                assert key in room_size.keys(), f"{key} is not in the room_size dict."
            config_all = room_size

        self.room_config = config_all["room_config"]
        self.object_transition_config = config_all["object_transition_config"]
        self.object_init_config = config_all["object_init_config"]
        self.deterministic_init = deterministic_init

        if "grid" in config_all.keys():
            self.grid = config_all["grid"]
        if "room_indexes" in config_all.keys():
            self.room_indexes = config_all["room_indexes"]
        if "names" in config_all.keys():
            self.names = config_all["names"]

        self.seed = seed
        seed_everything(self.seed)
        self.question_prob = question_prob
        self.terminates_at = terminates_at
        self.randomize_observations = randomize_observations
        self.total_episode_rewards = self.terminates_at + 1

        self._create_rooms()
        self._compute_room_map()
        self._create_objects()

        # Our state / action spaces are not tensors. Here we just make a dummy spaces
        # to bypass the gymnasium sanity check.
        self.observation_space = gym.spaces.Discrete(1)
        self.action_space = gym.spaces.Discrete(1)

        self.CORRECT = 1
        self.WRONG = -1
        self.relations = ["north", "east", "south", "west", "atlocation"]

        self.entities = (
            [obj.name for _, objs in self.objects.items() for obj in objs]
            + [room_name for room_name in self.rooms]
            + ["wall"]
        )

        self.hidden_global_states_all = []
        self.observations_all = []
        self.answers_all = []
        self.info_all = []

    def _create_rooms(self) -> None:
        """Create rooms."""
        self.rooms = {}
        for name, config_ in self.room_config.items():
            self.rooms[name] = Room(name, **config_)

    def _create_objects(self) -> None:
        """Create objects."""
        self.objects = {"static": [], "independent": [], "dependent": [], "agent": []}

        for name, init_probs in self.object_init_config["static"].items():
            self.objects["static"].append(
                StaticObject(
                    name,
                    init_probs,
                    self.object_transition_config["static"][name],
                    self.deterministic_init,
                )
            )

        for name, init_probs in self.object_init_config["independent"].items():
            self.objects["independent"].append(
                IndepdentObject(
                    name,
                    init_probs,
                    self.object_transition_config["independent"][name],
                    self.rooms,
                    self.deterministic_init,
                )
            )

        for name, init_probs in self.object_init_config["dependent"].items():
            self.objects["dependent"].append(
                DependentObject(
                    name,
                    init_probs,
                    self.object_transition_config["dependent"][name],
                    self.objects["independent"],
                    self.deterministic_init,
                )
            )

        for name, init_probs in self.object_init_config["agent"].items():
            self.objects["agent"].append(
                Agent(
                    "agent",
                    init_probs,
                    self.object_transition_config["agent"][name],
                    self.rooms,
                    self.deterministic_init,
                )
            )

    def _compute_room_map(self) -> None:
        """Get the room layout for semantic knowledge."""
        self.room_layout = []
        for name, room in self.rooms.items():
            self.room_layout.append([name, "north", room.north])
            self.room_layout.append([name, "east", room.east])
            self.room_layout.append([name, "south", room.south])
            self.room_layout.append([name, "west", room.west])

    def return_room_layout(self) -> list[list[str]]:
        """Return the room layout for semantic knowledge. Walls are not included."""
        room_layout = [
            deepcopy(triple) for triple in self.room_layout if triple[2] != "wall"
        ]

        return room_layout

    def _compute_hidden_global_state(self) -> None:
        """Get global hidden state, i.e., list of quadruples, of the environment.

        quadruples: [head, relation, tail, time]
        This is basically what the agent does not see and wants to estimate.

        """
        self.hidden_global_state = []

        for obj_type in ["agent", "static", "independent", "dependent"]:
            for obj in self.objects[obj_type]:
                self.hidden_global_state.append([obj.name, "atlocation", obj.location])

        for name, room in self.rooms.items():
            self.hidden_global_state.append([name, "north", room.north])
            self.hidden_global_state.append([name, "east", room.east])
            self.hidden_global_state.append([name, "south", room.south])
            self.hidden_global_state.append([name, "west", room.west])

        for triple in self.hidden_global_state:
            triple.append((self.current_time))

        self.hidden_global_states_all.append(deepcopy(self.hidden_global_state))

    def get_observations_and_question(self) -> dict:
        """Return what the agent sees in quadruples, and the question.

        At the moment, the questions are all one-hop queries. The first observation
        is always the agent's location. Use this wisely.

        Returns:
            observations_room: [head, relation, tail, current_time]
            question: [head, relation, tail, current_time], where either head or tail is "?"

        """
        # I don't think we need this anymore.
        # if self.current_time > self.terminates_at:
        #     self.observations_room = None
        #     self.question = None
        #     self.answers = None

        #     observations = {"room": None, "question": None}
        #     answers = None

        #     self.observations_all.append(observations)
        #     self.answers_all.append(answers)
        #     return None

        agent_location = self.objects["agent"][0].location
        self._compute_hidden_global_state()
        self.observations_room = []

        for quadruple in self.hidden_global_state:  # atm, there are only 5 relations.
            if quadruple[1] == "atlocation":
                if quadruple[2] == agent_location:
                    self.observations_room.append(quadruple)
            elif quadruple[1] in ["north", "east", "south", "west"]:
                if quadruple[0] == agent_location:
                    self.observations_room.append(quadruple)
            else:
                raise ValueError("Unknown relation.")

        question_candidates = [
            quadruple
            for quadruple in self.hidden_global_state
            # We don't want to ask a question about the agent and walls.
            if quadruple[0] != "agent" and quadruple[1] == "atlocation"
        ]

        self.question = random.choice(question_candidates)

        idx = random.choice([0, 2])  # we don't ask a qusetion about the relation.
        self.question = self.question[:idx] + ["?"] + self.question[idx + 1 :]

        self.answers = []
        for quadruple in self.hidden_global_state:
            if self.question[0] == "?":
                if (
                    quadruple[0] != "agent"
                    and quadruple[1] == self.question[1]
                    and quadruple[2] == self.question[2]
                ):
                    self.answers.append(quadruple[0])
            elif self.question[2] == "?":
                if (
                    quadruple[0] == self.question[0]
                    and quadruple[1] == self.question[1]
                ):
                    self.answers.append(quadruple[2])
            else:
                raise ValueError(f"Unknown question: {self.question}")

        if random.random() >= self.question_prob:
            self.question = None

        if self.randomize_observations:
            random.shuffle(self.observations_room)

        observations = {
            "room": deepcopy(self.observations_room),
            "question": deepcopy(self.question),
        }
        answers = deepcopy(self.answers)
        self.observations_all.append(observations)
        self.answers_all.append(answers)

        return observations

    def reset(self) -> tuple[tuple[list, list], dict]:
        """Reset the environment.


        Returns:
            state, info

        """
        info = {}
        self._create_rooms()
        self._create_objects()
        self.current_time = 0
        self.info_all.append(info)
        return self.get_observations_and_question(), info

    def step(self, actions: tuple[str, str]) -> tuple[tuple, int, bool, dict]:
        """An agent takes a set of actions.

        Args:
            actions:
                action_qa: An answer to the question.
                action_explore: An action to explore the environment, i.e., where to go.
                    north, east, south, west, or stay.

        Returns:
            (observation, question), reward, truncated, done, info

        """
        action_qa, action_explore = actions
        if action_qa in self.answers:
            reward = self.CORRECT
        else:
            reward = self.WRONG

        for obj in self.objects["independent"]:
            obj.move()

        for obj in self.objects["dependent"]:
            obj.attach()

        self.objects["agent"][0].move(action_explore)

        if self.current_time == self.terminates_at:
            done = True
        else:
            done = False

        truncated = False
        info = deepcopy({"answers": self.answers, "timestamp": self.current_time})
        self.info_all.append(info)

        self.current_time += 1

        return self.get_observations_and_question(), reward, done, truncated, info

    def _find_objects_in_room(self, room_name: str) -> dict[str, list]:
        """Find objects in a room.

        Args:
            room_name: room name

        Returns:
            objects_in_room: objects in the room

        """
        objects_in_room = {obj_type: [] for obj_type in self.objects.keys()}
        for obj_type, objects in self.objects.items():
            for obj in objects:
                if obj.location == room_name:
                    objects_in_room[obj_type].append(obj.name)

        return objects_in_room

    def render(
        self,
        render_mode: str = "console",
        figsize: tuple[int, int] = (15, 15),
        cell_text_size: int = 10,
        save_fig_dir: str = None,
        image_format: str = "png",
    ) -> None:
        """Render the environment."""
        if render_mode == "console":
            pprint(self.hidden_global_state)
        elif render_mode == "image":
            if self.is_notebook:
                clear_output(True)
            plt.figure(figsize=figsize)
            num_rows = len(self.grid)
            num_cols = len(self.grid[0])

            plt.subplot(111)
            plt.title(f"Hidden state at time={self.current_time}")

            for row in range(num_rows):
                for col in range(num_cols):
                    text = ""
                    cell_content = self.grid[row][col]
                    if cell_content != 0:
                        color = "white"
                        room_index = self.room_indexes.index([row, col])
                        room_name = self.names["room"][room_index]
                        text += f"room name={room_name}"

                        objects_in_room = self._find_objects_in_room(room_name)
                        for obj_type, objects in objects_in_room.items():
                            if len(objects) > 0:
                                text += f"\n{obj_type} objects: {objects}"

                    else:
                        color = "black"
                    plt.gca().add_patch(
                        plt.Rectangle((col, num_rows - 1 - row), 1, 1, facecolor=color)
                    )
                    plt.text(
                        col + 0.5,
                        num_rows - 1 - row + 0.5,
                        text,
                        ha="center",
                        va="center",
                        color="black",
                        fontsize=cell_text_size,
                    )
            plt.gca().set_aspect("equal")
            plt.gca().set_xticks(range(num_cols + 1))
            plt.gca().set_yticks(range(num_rows + 1))
            plt.gca().grid(which="both")

            if save_fig_dir is not None:
                os.makedirs(save_fig_dir, exist_ok=True)
                plt.savefig(
                    os.path.join(
                        save_fig_dir,
                        f"hidden_state-"
                        f"{str(self.current_time).zfill(3)}.{image_format}",
                    )
                )
            plt.show()
